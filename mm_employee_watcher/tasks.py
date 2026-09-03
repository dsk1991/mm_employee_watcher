"""Scheduled jobs registered in hooks.py.

check_expired_sessions   -> the "2:00 PM" flow: server-side state change +
                             frappe.publish_realtime, every minute.
check_offline_employees  -> heartbeat watchdog: a dropped connection/closed
                             app becomes OFFLINE, never silently IDLE.
"""

import frappe
from frappe.utils import now_datetime

from mm_employee_watcher.mm_employee_watcher.utils import (
	STATUS_IDLE,
	STATUS_OFFLINE,
	STATUS_WORKING,
	STATUS_BREAK,
	STATUS_BLOCKED,
	SESSION_ACTIVE,
	SESSION_EXTENDED,
	set_status,
	get_or_create_status,
	is_tracking_enabled,
	log_event,
	offline_cutoff,
)


def check_expired_sessions():
	"""Find Employee Work Sessions whose target_end_time has passed and are
	still Active/Extended, and push a realtime alert to the employee.

	This does NOT auto-complete the session — the employee still has to
	pick Done / Extend / Blocked (design doc section 3). It only fires the
	notification (and, via FCM, would reach a closed mobile app too — see
	docs/backend-architecture.md section 8; FCM delivery is not wired up
	in this foundation cut).
	"""
	expired = frappe.get_all(
		"Employee Work Session",
		filters={
			"status": ["in", [SESSION_ACTIVE, SESSION_EXTENDED]],
			"target_end_time": ["<", now_datetime()],
		},
		fields=["name", "employee", "work_activity", "target_qty", "completed_qty", "target_end_time"],
	)

	for session in expired:
		if not is_tracking_enabled(session.employee):
			continue
		frappe.publish_realtime(
			event="mm_employee_watcher:session_expired",
			message={
				"work_session": session.name,
				"employee": session.employee,
				"work_activity": session.work_activity,
				"target_qty": session.target_qty,
				"completed_qty": session.completed_qty,
				"target_end_time": session.target_end_time,
			},
			user=frappe.db.get_value("Employee", session.employee, "user_id"),
		)
		# Also let the supervisor dashboard know this one is now overdue.
		frappe.publish_realtime(
			event="mm_employee_watcher:dashboard_update",
			message={"employee": session.employee, "work_session": session.name, "overdue": True},
		)


def check_offline_employees():
	"""Employees whose last heartbeat is older than OFFLINE_AFTER_MINUTES,
	and who are not on an authorized BREAK or already OFFLINE/OFF DUTY,
	get flipped to OFFLINE rather than being silently counted as idle."""
	cutoff = offline_cutoff()

	stale = frappe.get_all(
		"Employee Current Status",
		filters={
			"status": ["in", [STATUS_WORKING, STATUS_IDLE, STATUS_BLOCKED]],
			"last_heartbeat": ["<", cutoff],
		},
		fields=["employee", "current_session"],
	)

	for row in stale:
		if not is_tracking_enabled(row.employee):
			continue
		if row.current_session:
			log_event(row.employee, row.current_session, "Idle Start", remarks="no heartbeat")
		set_status(row.employee, STATUS_OFFLINE, None)
