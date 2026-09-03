"""Runs once on `bench --site your-site install-app mm_employee_watcher`."""

import frappe

APP_ROLES = (
	("Employee Watcher Manager", 1),
	("Employee Watcher Viewer", 1),
)

DEFAULT_SECTIONS = (
	("Sales Office", "Work", 120),
	("Sales Warehouse", "Work", 120),
	("Break", "Break", 30),
)

DEFAULT_ACTIVITIES = (
	("Sales Invoice Creation", "Sales Office", 60),
	("Payment Entry", "Sales Office", 45),
	("Report Viewing", "Sales Office", 30),
	("Picking", "Sales Warehouse", 60),
	("Putaway", "Sales Warehouse", 60),
	("Stock Counting", "Sales Warehouse", 60),
	("Packing", "Sales Warehouse", 60),
)


def before_install():
	create_app_roles()


def before_migrate():
	create_app_roles()


def after_install():
	setup_required_records()


def after_migrate():
	"""Keep upgrades idempotent for sites that installed an older release."""
	setup_required_records()


def setup_required_records():
	create_user_tracking_field()
	create_app_roles()
	create_default_sections_and_activities()


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


def create_default_sections_and_activities():
	"""Provide useful defaults without overwriting a site's own masters."""
	for section_name, section_type, duration in DEFAULT_SECTIONS:
		if frappe.db.exists("Work Section Master", section_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Work Section Master",
				"section_name": section_name,
				"section_type": section_type,
				"default_duration_minutes": duration,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)

	for activity_name, work_section, duration in DEFAULT_ACTIVITIES:
		if not frappe.db.exists("Work Activity Master", activity_name):
			frappe.get_doc(
				{
					"doctype": "Work Activity Master",
					"activity_name": activity_name,
					"work_section": work_section,
					"default_duration_minutes": duration,
				}
			).insert(ignore_permissions=True)
			continue
		if not frappe.db.get_value("Work Activity Master", activity_name, "work_section"):
			frappe.db.set_value(
				"Work Activity Master", activity_name, "work_section", work_section
			)


def run_if_not_already_installed():
	"""For an app that was installed before this hook existed — run once
	by hand: `bench --site your-site execute
	mm_employee_watcher.install.run_if_not_already_installed`"""
	setup_required_records()
