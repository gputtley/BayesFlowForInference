import yaml
import numpy as np

from useful_functions import MakeDirectories, GetYName
from plotting import plot_likelihood

class ScanPlot():

  def __init__(self):
    """
    A template class.
    """
    self.column = None

    self.data_input = "data"
    self.plots_output = "data"    
    self.extra_file_name = ""
    self.other_input = {}
    self.verbose = True

  def Configure(self, options):
    """
    Configure the class settings.

    Args:
        options (dict): Dictionary of options to set.
    """
    for key, value in options.items():
      setattr(self, key, value)

    if self.extra_file_name != "":
      self.extra_file_name = f"_{self.extra_file_name}"

  def Run(self):
    """
    Run the code utilising the worker classes
    """
    scan_results_file = f"{self.data_input}/scan_results_{self.column}{self.extra_file_name}.yaml"

    with open(scan_results_file, 'r') as yaml_file:
      scan_results = yaml.load(yaml_file, Loader=yaml.FullLoader)

    x = scan_results["scan_values"]
    y = scan_results["nlls"]
    crossings = scan_results["crossings"]
    row = scan_results["row"]
    ind = scan_results["columns"].index(self.column)

    other_lklds = {}
    for key, val in self.other_input.items():
      other_scan_file = f"{val}/scan_results_{self.column}{self.extra_file_name}.yaml"
      with open(other_scan_file, 'r') as yaml_file:
        other_scan_results = yaml.load(yaml_file, Loader=yaml.FullLoader)
      other_lklds[key] = [other_scan_results["scan_values"], other_scan_results["nlls"]]

    file_extra_name = GetYName(row, purpose="file")
    plot_extra_name = GetYName(row, purpose="plot")
    
    plot_likelihood(
      x, 
      y, 
      crossings, 
      name = f"{self.plots_output}/likelihood_scan_{self.column}{self.extra_file_name}", 
      xlabel = self.column, 
      true_value = row[ind],
      title_right = f"y={plot_extra_name}" if plot_extra_name != "" else "",
      cap_at = 9,
      label = None if len(list(other_lklds.keys())) == 0 else "Nominal",
      other_lklds=other_lklds,
    )

  def Outputs(self):
    """
    Return a list of outputs given by class
    """
    outputs = []
    return outputs

  def Inputs(self):
    """
    Return a list of inputs required by class
    """
    inputs = []
    return inputs
