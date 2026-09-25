"""0.5.0 - shifts now come from HRMS (Shift Type / Shift Assignment), so the
short-lived own Work Shift doctype and the Employee.mm_work_shift field go.
Best effort and idempotent."""

import frappe


def execute():
	name = frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "mm_work_shift"})
	if name:
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	if frappe.db.exists("DocType", "Work Shift"):
		try:
			frappe.delete_doc("DocType", "Work Shift", ignore_permissions=True, force=True)
		except Exception:
			frappe.log_error(title="MM Employee Watcher: could not remove Work Shift", message=frappe.get_traceback())
