// Copyright (c) 2024, pibiCo and contributors
// For license information, please see license.txt

frappe.ui.form.on('CN Device', {
    refresh: function(frm) {
        frm.remove_custom_button(frappe.utils.icon("reply", "sm"));
        frm.add_custom_button(frappe.utils.icon("reply", "sm"), function() {
            window.location.href = '/app/pibiconnect';
        });
    }
});
