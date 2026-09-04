"""Runs once on `bench --site your-site install-app mm_employee_watcher`."""

import frappe

APP_ROLES = (
	("Employee Watcher Manager", 1),
	("Employee Watcher Viewer", 1),
)

DEFAULT_ACTIVITIES = (
	("Sales Invoice Creation", 60),
	("Payment Entry", 45),
	("Report Viewing", 30),
	("Picking", 60),
	("Putaway", 60),
	("Stock Counting", 60),
	("Packing", 60),
)

TRACKED_DOCTYPES = {
	"Work Activity Master": "work_activity_master",
	"Employee Work Session": "employee_work_session",
	"Employee Work Log": "employee_work_log",
	"Employee Work Queue": "employee_work_queue",
	"Employee Current Status": "employee_current_status",
	"Employee Watcher Alert": "employee_watcher_alert",
	"MM Watcher Settings": "mm_watcher_settings",
	"MM Watcher Alert Recipient": "mm_watcher_alert_recipient",
	"Work Queue Schedule": "work_queue_schedule",
	"Work Queue Schedule Assignee": "work_queue_schedule_assignee",
}


def before_install():
	create_app_roles()


def before_migrate():
	repair_doctype_modules()
	create_app_roles()


def after_install():
	setup_required_records()


def after_migrate():
	"""Keep upgrades idempotent for sites that installed an older release."""
	repair_doctype_modules()
	setup_required_records()


def repair_doctype_modules():
	"""Fix stale DocType module metadata that can break controller import on upgrade.

	Older installs may keep legacy module values like
	`frappe.core.doctype.work_activity_master`; this forces the module back to
	this app so migration can complete and default records can be seeded.
	"""
	target_module = "MM Employee Watcher"
	changed_doctypes = []

	for doctype_name in TRACKED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype_name):
			continue
		existing_module = frappe.db.get_value("DocType", doctype_name, "module")
		if existing_module == target_module:
			continue

		frappe.db.set_value("DocType", doctype_name, "module", target_module)
		changed_doctypes.append(doctype_name)

	# Frappe caches both DocType-to-module mappings and imported controllers for
	# the lifetime of the migrate process. Clear those process-local caches so a
	# DocType previously saved under Core is not imported as frappe.core.*.
	frappe.cache.delete_value("doctype_modules")
	if changed_doctypes:
		from frappe.model.base_document import site_controllers
		from frappe.modules.utils import doctype_python_modules

		for doctype_name in changed_doctypes:
			site_controllers.pop(doctype_name, None)
			for key in tuple(doctype_python_modules):
				if len(key) > 1 and key[1] == doctype_name:
					doctype_python_modules.pop(key, None)

	frappe.clear_cache()


def setup_required_records():
	create_user_tracking_field()
	create_app_roles()
	create_default_activities()


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


def create_app_roles():
	for role_name, desk_access in APP_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": desk_access,
			}
		).insert(ignore_permissions=True)


def create_default_activities():
	"""Provide useful defaults without overwriting a site's own masters."""
	for activity_name, duration in DEFAULT_ACTIVITIES:
		if frappe.db.exists("Work Activity Master", activity_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Work Activity Master",
				"activity_name": activity_name,
				"default_duration_minutes": duration,
			}
		).insert(ignore_permissions=True)


def run_if_not_already_installed():
	"""For an app that was installed before this hook existed — run once
	by hand: `bench --site your-site execute
	mm_employee_watcher.install.run_if_not_already_installed`"""
	setup_required_records()
