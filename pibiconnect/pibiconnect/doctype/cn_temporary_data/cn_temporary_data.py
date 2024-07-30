# Copyright (c) 2024, pibiCo and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

# Global temporary data store
temporary_data_store = []

class CNTemporaryData(Document):
    def __init__(self, *args, **kwargs):
        super(CNTemporaryData, self).__init__(*args, **kwargs)
        if not self.timestamp:
            self.timestamp = now_datetime()

    def db_insert(self, *args, **kwargs):
        temporary_data_store.append(self)

    def load_from_db(self):
        # This method is called when frappe.get_doc is used
        # We'll search our temporary store instead of the database
        for data in temporary_data_store:
            if data.name == self.name:
                self.update(data)
                break

    def db_update(self, *args, **kwargs):
        # Update the document in our temporary store
        for i, data in enumerate(temporary_data_store):
            if data.name == self.name:
                temporary_data_store[i] = self
                break

    def delete(self):
        # Remove the document from our temporary store
        global temporary_data_store
        temporary_data_store = [data for data in temporary_data_store if data.name != self.name]

    @staticmethod
    def get_list(args):
        # This method is called when frappe.get_list is used
        # We'll filter our temporary store based on the args
        def match_filters(doc, filters):
            for f in filters:
                key, value = f[0], f[1]
                if isinstance(value, (list, tuple)):
                    if value[0] == 'between':
                        if not (value[1][0] <= getattr(doc, key) <= value[1][1]):
                            return False
                    elif value[0] == '=':
                        if getattr(doc, key) != value[1]:
                            return False
                    # Add more conditions as needed
                elif getattr(doc, key) != value:
                    return False
            return True

        filters = args.get('filters', [])
        filtered_data = [d for d in temporary_data_store if match_filters(d, filters)]

        # Apply limit and order
        limit = args.get('limit_page_length', len(filtered_data))
        start = args.get('limit_start', 0)
        return filtered_data[start:start+limit]

    @staticmethod
    def get_count(args):
        # Return the count of documents matching the filters
        filters = args.get('filters', [])
        return len([d for d in temporary_data_store if match_filters(d, filters)])

    @staticmethod
    def get_stats(args):
        # This method can be implemented if you need specific stats
        # For now, we'll just return a placeholder
        return {}

def clear_old_data(minutes=60):
    # Function to clear data older than the specified number of minutes
    global temporary_data_store
    cutoff_time = frappe.utils.add_to_date(now_datetime(), minutes=-minutes)
    temporary_data_store = [data for data in temporary_data_store if data.timestamp > cutoff_time]
