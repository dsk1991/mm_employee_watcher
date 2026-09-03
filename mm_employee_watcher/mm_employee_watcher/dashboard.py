"""Data for the wall-display Supervisor Dashboard (www/mm_dashboard.html).

One whitelisted call the page's JS re-fetches every 30 seconds — see
docs/backend-architecture.md section 6.
"""

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds

# WORKING/BLOCKED employees are the ones a supervisor most needs to see
# first — blocked (needs help right now) even before working.
STATUS_ORDER = {"BLOCKED": 0, "WORKING": 1, "BREAK": 2, "IDLE": 3, "OFFLINE": 4, "OFF DUTY": 5}


@frappe.whitelist()
def get_dashboard_data():
	rows = frappe.get_all(
		"Employee Current Status",
		fields=["employee", "employee_name", "status", "status_since", "current_session"],
	)

	now = now_datetime()
	cards = []
	for row in rows:
		card = {
			"employee": row.employee,
			"employee_name": row.employee_name or row.employee,
			"status": row.status,
			"since_minutes": (
				int(time_diff_in_seconds(now, row.status_since) // 60) if row.status_since else None
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
				if session.target_end_time:
					card["remaining_minutes"] = int(
						time_diff_in_seconds(session.target_end_time, now) // 60
					)

		cards.append(card)

	cards.sort(key=lambda c: (STATUS_ORDER.get(c["status"], 9), c["employee_name"]))

	counts = {}
	for c in cards:
		counts[c["status"]] = counts.get(c["status"], 0) + 1

	return {"generated_at": now, "cards": cards, "counts": counts}
