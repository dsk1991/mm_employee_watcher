"""Runs once on `bench --site your-site install-app mm_employee_watcher`."""

import frappe


def after_install():
	create_user_tracking_field()


def create_user_tracking_field():
	"""Requirement #4: a per-user on/off switch for tracking, living on the
	User doctype as a Custom Field (so it survives framework upgrades and
	shows up on the standard User form with no extra UI work)."""
	if frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "mm_tracking_enabled"}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "User",
			"fieldname": "mm_tracking_enabled",
			"label": "Enable Work Tracking (MM Employee Watcher)",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "enabled",
			"description": (
				"Uncheck to stop MM Employee Watcher from tracking this user's "
				"work sessions — e.g. for admins, supervisors, or any role that "
				"shouldn't be tracked as WORKING/IDLE/BREAK."
			),
		}
	).insert(ignore_permissions=True)


def run_if_not_already_installed():
	"""For an app that was installed before this hook existed — run once
	by hand: `bench --site your-site execute
	mm_employee_watcher.install.run_if_not_already_installed`"""
	create_user_tracking_field()
