import copy
import yaml

import numpy as np
import pandas as pd

from functools import partial

from useful_functions import MakeDirectories, GetYName, SplitValidationParameters

class PerformanceMetrics():

  def __init__(self):
    """
    A template class.
    """
    # Default values - these will be set by the configure function
    self.model = None
    self.parameters = None
    self.architecture = None
    self.val_loop = []
    self.pois = None
    self.nuisances = None
    self.cfg_name = None
  
    self.data_output = "data/"
    self.verbose = True
    self.do_loss = True
    self.do_chi_squared = False
    self.do_bdt_separation = False
    self.do_inference = True
    self.inference_datasets = ["test_inf","val"]
    self.test_name = "test"
    self.save_extra_name = ""
    self.split_validation_files = False

  def Configure(self, options):
    """
    Configure the class settings.

    Args:
        options (dict): Dictionary of options to set.
    """
    for key, value in options.items():
      setattr(self, key, value)

  def Run(self):
    """
    Run the code utilising the worker classes
    """
    # Open parameters
    if self.verbose:
      print("- Loading in the parameters")
    with open(self.parameters, 'r') as yaml_file:
      parameters = yaml.load(yaml_file, Loader=yaml.FullLoader)

    # Load the architecture in
    if self.verbose:
      print("- Loading in the architecture")
    with open(self.architecture, 'r') as yaml_file:
      architecture = yaml.load(yaml_file, Loader=yaml.FullLoader)

    # Build model
    if self.verbose:
      print("- Building the model")
    from network import Network
    network = Network(
      f"{parameters['file_loc']}/X_train.parquet",
      f"{parameters['file_loc']}/Y_train.parquet", 
      f"{parameters['file_loc']}/wt_train.parquet", 
      f"{parameters['file_loc']}/X_{self.test_name}.parquet",
      f"{parameters['file_loc']}/Y_{self.test_name}.parquet", 
      f"{parameters['file_loc']}/wt_{self.test_name}.parquet",
      options = {
        **architecture,
        **{
          "data_parameters" : parameters
        }
      }
    )  
    
    # Loading model
    if self.verbose:
      print("- Loading the model")
    network.Load(name=self.model)

    # Set up metrics dictionary
    metrics = {} 

    # Get the loss values
    if self.do_loss:
      if self.verbose:
        print("- Getting the losses")
      metrics["loss_train"] = network.GetLoss(dataset="train")
      metrics["loss_test"] = network.GetLoss(dataset="test")
      if self.verbose:
        print(f"  - Train loss: {metrics['loss_train']}")
        print(f"  - Test loss: {metrics['loss_test']}")

    # Get BDT separation metric
    if self.do_bdt_separation:
      if self.verbose:
        print("- Getting BDT separation")
      metrics["bdt_separation_train"] = network.GetAUC(dataset="train")
      metrics["bdt_separation_test"] = network.GetAUC(dataset="test")


    # Get histogram metrics to run
    histogram_metrics = []
    if self.do_chi_squared:
      histogram_metrics.append("chi_squared")

    if len(histogram_metrics):
      if self.verbose:
        print("- Getting histogram metrics")
      hist_metrics = network.GetHistogramMetric(metric=histogram_metrics)

      # Add hist_metric sums
      summed_hist_metrics = {}
      for metric_name, metric_results in hist_metrics.items():
        summed_hist_metrics[metric_name] = {"total":0.0}
        for k1, v1 in metric_results.items():
          for k2, v2 in v1.items():
            summed_hist_metrics[metric_name]["total"] += v2
            k1_sum_name = f"{k1}_sum"
            k2_sum_name = f"{k2}_sum"
            if k1_sum_name not in summed_hist_metrics[metric_name].keys():
              summed_hist_metrics[metric_name][k1_sum_name] = v2*1.0
            else:
              summed_hist_metrics[metric_name][k1_sum_name] += v2
            if k2_sum_name not in summed_hist_metrics[metric_name].keys():
              summed_hist_metrics[metric_name][k2_sum_name] = v2*1.0
            else:
              summed_hist_metrics[metric_name][k2_sum_name] += v2
        hist_metrics[metric_name] = {**hist_metrics[metric_name], **summed_hist_metrics[metric_name]}

      metrics = {**metrics, **hist_metrics}

    if self.do_inference and len(parameters["Y_columns"]) > 0:

      if self.verbose:
        print("- Getting chi squared from quick inference")


      for inf_test_name in self.inference_datasets:
      
        # Build yields
        from yields import Yields
        eff_events_class = Yields(
          pd.read_parquet(parameters['yield_loc']), 
          self.pois, 
          self.nuisances, 
          parameters["file_name"],
          method="default", 
          column_name=f"effective_events_{inf_test_name}"
        )

        # Build likelihood
        from likelihood import Likelihood
        lkld = Likelihood(
          {
            "pdfs" : {parameters["file_name"] : network},
          },
          likelihood_type = "unbinned", 
          data_parameters = {parameters["file_name"] : parameters},
        )

        # Loop through validation values
        orig_parameters = copy.deepcopy(parameters)
        inf_chi_squared = {}
        inf_dist = {}
        for loop_ind, loop in enumerate(self.val_loop):

          if self.split_validation_files:
            cfg = {"files" : {parameters["file_name"] : None}, "name" : self.cfg_name}
            parameters_file_name = SplitValidationParameters(loop, parameters["file_name"], loop_ind, cfg)
            with open(parameters_file_name, 'r') as yaml_file:
              parameters = yaml.load(yaml_file, Loader=yaml.FullLoader)

          if self.verbose:
            print(f"- Running unbinned likelihood fit for the {inf_test_name} dataset and Y:")
            print(loop["row"])

          # Build test data loader
          from data_processor import DataProcessor
          dps = DataProcessor(
            [[f"{parameters['file_loc']}/X_{inf_test_name}.parquet", f"{parameters['file_loc']}/Y_{inf_test_name}.parquet", f"{parameters['file_loc']}/wt_{inf_test_name}.parquet"]],
            "parquet",
            wt_name = "wt",
            options = {
              "parameters" : parameters,
              "selection" : " & ".join([f"({col}=={loop['row'].loc[:,col].iloc[0]})" for col in loop['row'].columns]),
              "scale" : eff_events_class.GetYield(loop["row"]),
              "functions" : ["untransform"]
            }
          )

          # Skip if empty
          if dps.GetFull(method="count") == 0: continue

          # Do initial fit
          lkld.GetBestFit([dps], loop["initial_best_fit_guess"])

          # Get uncertainty
          y_name = GetYName(loop['row'], purpose="file")
          inf_chi_squared[y_name] = {}
          inf_dist[y_name] = {}
          for col in loop['row'].columns:
            if self.verbose:
              print(f"- Finding uncertainty estimates for {col}")
            uncert = lkld.GetApproximateUncertainty([dps], col)
            col_index = list(loop['row'].columns).index(col)
            true_value = float(loop['row'].loc[0,col])
            if true_value > lkld.best_fit[col_index]:
              inf_chi_squared[y_name][col] = float(((true_value - lkld.best_fit[col_index])**2) / (uncert[1]**2))
            else:
              inf_chi_squared[y_name][col] = float(((true_value - lkld.best_fit[col_index])**2) / (uncert[-1]**2))
            inf_dist[y_name][col] = abs(float(true_value - lkld.best_fit[col_index]))

        # Reset parameters
        parameters = copy.deepcopy(orig_parameters)

        # Get chi squared values
        total_sum = 0.0
        total_count = 0.0
        for val_name, val_dict in inf_chi_squared.items():
          total_sum += np.sum(list(val_dict.values()))
          total_count += len(list(val_dict.values()))
          inf_chi_squared[val_name]["all"] = float(np.sum(list(val_dict.values())))/len(list(val_dict.values()))
        inf_chi_squared["all"] = float(total_sum/total_count)
        metrics[f"inference_chi_squared_{inf_test_name}"] = inf_chi_squared

        # Get distance values
        total_sum = 0.0
        total_count = 0.0
        for val_name, val_dict in inf_dist.items():
          total_sum += np.sum(list(val_dict.values()))
          total_count += len(list(val_dict.values()))
          inf_dist[val_name]["all"] = float(np.sum(list(val_dict.values())))/len(list(val_dict.values()))
        inf_dist["all"] = float(total_sum/total_count)
        metrics[f"inference_distance_{inf_test_name}"] = inf_dist

    # Write to yaml
    if self.verbose:
      print("- Writing metrics yaml")
    output_name = f"{self.data_output}/metrics{self.save_extra_name}.yaml"
    MakeDirectories(output_name)
    with open(output_name, 'w') as yaml_file:
      yaml.dump(metrics, yaml_file, default_flow_style=False) 

    # Print metrics
    for metric in sorted(list(metrics.keys())):
      if not isinstance(metrics[metric], dict):
        print(f"{metric} : {metrics[metric]}")
      else:
        print(f"{metric} :")
        for k1 in sorted(list(metrics[metric].keys())):
          if not isinstance(metrics[metric][k1], dict):
            print(f"  {k1} : {metrics[metric][k1]}")
          else:
            print(f"  {k1} :")
            for k2 in sorted(list(metrics[metric][k1].keys())):
              print(f"    {k2} : {metrics[metric][k1][k2]}")          


  def Outputs(self):
    """
    Return a list of outputs given by class
    """
    outputs = [
      f"{self.data_output}/metrics{self.save_extra_name}.yaml"
    ]
    return outputs

  def Inputs(self):
    """
    Return a list of inputs required by class
    """
    with open(self.parameters, 'r') as yaml_file:
      parameters = yaml.load(yaml_file, Loader=yaml.FullLoader)
    inputs = [
      self.model,
      self.architecture,
      self.parameters,
      f"{parameters['file_loc']}/X_train.parquet",
      f"{parameters['file_loc']}/Y_train.parquet", 
      f"{parameters['file_loc']}/wt_train.parquet", 
      f"{parameters['file_loc']}/X_{self.test_name}.parquet",
      f"{parameters['file_loc']}/Y_{self.test_name}.parquet", 
      f"{parameters['file_loc']}/wt_{self.test_name}.parquet",
    ]
    return inputs

        