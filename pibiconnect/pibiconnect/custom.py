# -*- coding: utf-8 -*-
# Copyright (c) 2024, PibiCo and contributors
# For license information, please see license.txt
import frappe
from frappe import _
import datetime

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
CHART_FORMAT = "%H:%M"

@frappe.whitelist()
def get_chart(doc):
  if not doc.startswith('new-'):
    data = frappe.get_doc("CN Device Log", doc)
    if data.log_item:
      sensor_vars = {}
      for item in data.log_item:
        var = item.sensor_var
        if var not in sensor_vars:
          sensor_vars[var] = {
            "var": var,
            "uom": item.uom,
            "labels": [],
            "readings": []
          }
        sensor_vars[var]["labels"].append(item.data_date.strftime(CHART_FORMAT))
        try:
          value = float(item.value)
        except (ValueError, TypeError):
          value = 0  # Handle non-numeric or missing values
        sensor_vars[var]["readings"].append(value)
      
      # Calculate averages and prepare the final list
      result = []
      for var, details in sensor_vars.items():
        readings = details["readings"]
        average = sum(readings) / len(readings) if readings else 0
        details["average"] = [average] * len(readings)  # Repeat average for each label
        result.append(details)
      
      return result
  return []