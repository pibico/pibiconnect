# Copyright (c) 2024, pibiCo and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class CNSpan(Document):
    def validate(self):
        if not self.higher_span and not self.lower_span:
            self.span_factor = 1
            return
            
        value_range = self.higher_span - self.lower_span
        self.span_factor = value_range / 10
        
    def calculate_reading(self, voltage):
        """
        Calculate sensor reading from voltage input (0-10V)
        If no spans defined, returns raw voltage value
        Includes calibration factor offset of 0.30V
        """
        if not self.higher_span and not self.lower_span:
            return voltage
            
        calibration_factor = 0.00
        adjusted_voltage = max(0, voltage - calibration_factor)
        
        return self.lower_span + (adjusted_voltage * self.span_factor)