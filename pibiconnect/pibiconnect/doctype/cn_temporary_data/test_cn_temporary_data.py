# Copyright (c) 2024, pibiCo and Contributors
# See license.txt

import frappe
from frappe.model.document import Document

# In-memory storage for virtual doctype data
temporary_data_store = []

class CNTemporaryData(Document):
    def db_insert(self):
        # Override db_insert to insert data into in-memory storage
        temporary_data_store.append(self.as_dict())
    
    def load_from_db(self):
        # Load data from in-memory storage
        for record in temporary_data_store:
            if record['name'] == self.name:
                self.update(record)
                break
    
    def db_update(self):
        # Override db_update to update data in in-memory storage
        for record in temporary_data_store:
            if record['name'] == self.name:
                record.update(self.as_dict())
                break
    
    def delete(self):
        # Override delete to remove data from in-memory storage
        global temporary_data_store
        temporary_data_store = [record for record in temporary_data_store if record['name'] != self.name]

    @staticmethod
    def get_all():
        return temporary_data_store

    @staticmethod
    def clear():
        global temporary_data_store
        temporary_data_store = []