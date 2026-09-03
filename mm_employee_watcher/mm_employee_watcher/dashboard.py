"""Data for the wall-display Supervisor Dashboard (www/mm_dashboard.html).

One whitelisted call the page's JS re-fetches every 30 seconds — see
docs/backend-architecture.md section 6.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_seconds, today

from mm_employee_watcher.utils import is_tracking_enabled

# WORKING/BLOCKED employees are the ones a supervisor most needs to see
# first — blocked (needs help right now) even before working.
STATUS_ORDER = {"BLOCKED": 0, "WORKING": 1, "BREAK": 2, "IDLE": 3, "OFFLINE": 4, "OFF DUTY": 5}
DASHBOARD_ROLES = {"System Manager", "HR Manager", "Employee Watcher Manager", "Employee Watcher Viewer"}


@frappe.whitelist()
def get_dashboard_data():
	if not DASHBOARD_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("You do not have permission to view the employee dashboard"), frappe.PermissionError)

	rows = frappe.get_all(
		"Employee Current Status",
		fields=[
			"employee",
			"employee_name",
			"status",
			"status_since",
			"current_section",
			"current_section_session",
			"current_session",
		],
	)

	now = now_datetime()
	cards = []
	for row in rows:
		if not is_tracking_enabled(row.employee):
			continue
		card = {
			"employee": row.employee,
			"employee_name": row.employee_name or row.employee,
			"status": row.status,
			"work_section": row.current_section,
			"since_minutes": (
				max(0, int(time_diff_in_seconds(now, row.status_since) // 60)) if row.status_since else None
			),
		}

		if row.current_section_session:
			section = frappe.db.get_value(
				"Employee Section Session",
				row.current_section_session,
				["target_end_time", "start_time", "source_app", "extended_minutes"],
				as_dict=True,
			)
			if section:
				card["section_source_app"] = section.source_app
				card["section_extended_minutes"] = section.extended_minutes
				if section.target_end_time:
					card["section_remaining_minutes"] = int(
						time_diff_in_seconds(section.target_end_time, now) // 60
					)

		if row.current_session:
			session = frappe.db.get_value(
				"Employee Work Session",
				row.current_session,
				[
					"work_activity",
					"target_qty",
					"completed_qty",
					"target_end_time",
					"status",
					"extended_minutes",
					"blocked_reason",
					"source_app",
					"reference_doctype",
					"reference_name",
				],
				as_dict=True,
			)
			if session:
				card["work_activity"] = session.work_activity
				card["target_qty"] = session.target_qty
				card["completed_qty"] = session.completed_qty
				card["session_status"] = session.status
				card["extended_minutes"] = session.extended_minutes
				card["blocked_reason"] = session.blocked_reason
				card["source_app"] = session.source_app
				card["reference_doctype"] = session.reference_doctype
				card["reference_name"] = session.reference_name
				if session.target_end_time:
					card["remaining_minutes"] = int(
						time_diff_in_seconds(session.target_end_time, now) // 60
					)


		events = frappe.get_all(
			"Employee Work Log",
			filters={"employee": row.employee, "event_time": [">=", f"{today()} 00:00:00"]},
			fields=["event_type", "count(name) as event_count"],
			group_by="event_type",
		)
		card["today_counts"] = {event.event_type: event.event_count for event in events}
		cards.append(card)

	cards.sort(key=lambda c: (STATUS_ORDER.get(c["status"], 9), c["employee_name"]))

	counts = {}
	for c in cards:
		counts[c["status"]] = counts.get(c["status"], 0) + 1

	return {"generated_at": now, "cards": cards, "counts": counts}
