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
			"current_session",
		],
	)

	now = now_datetime()

	# Today's Work Log event counts per employee, in one grouped query.
	counts_by_employee = {}
	for log in frappe.db.sql(
		"""
		select employee, event_type, count(name) as event_count
		from `tabEmployee Work Log`
		where event_time >= %s
		group by employee, event_type
		""",
		(f"{today()} 00:00:00",),
		as_dict=True,
	):
		counts_by_employee.setdefault(log.employee, {})[log.event_type] = log.event_count

	cards = []
	for row in rows:
		if not is_tracking_enabled(row.employee):
			continue
		card = {
			"employee": row.employee,
			"employee_name": row.employee_name or row.employee,
			"status": row.status,
			"since_minutes": (
				max(0, int(time_diff_in_seconds(now, row.status_since) // 60)) if row.status_since else None
			),
		}

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
					"notes",
				],
				as_dict=True,
			)
			if session:
				card["work_activity"] = session.work_activity
				card["description"] = session.notes
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

		card["today_counts"] = counts_by_employee.get(row.employee, {})
		cards.append(card)

	cards.sort(key=lambda c: (STATUS_ORDER.get(c["status"], 9), c["employee_name"]))

	counts = {}
	for c in cards:
		counts[c["status"]] = counts.get(c["status"], 0) + 1

	return {"generated_at": now, "cards": cards, "counts": counts}
