"""Scheduled jobs registered in hooks.py.

check_expired_sessions   -> the "2:00 PM" flow: one-shot realtime alert for
                             each target time, every minute.
check_offline_employees  -> heartbeat watchdog: a dropped connection/closed
                             app becomes OFFLINE, never silently IDLE.
"""

import frappe
from frappe.utils import now_datetime, get_datetime

from mm_employee_watcher.utils import (
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
			"expiry_notified_at": ["is", "not set"],
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
		frappe.db.set_value(
			"Employee Work Session",
			session.name,
			"expiry_notified_at",
			now_datetime(),
			update_modified=False,
		)


def check_expired_sections():
	"""Notify once when an active section passes its server-side target."""
	expired = frappe.get_all(
		"Employee Section Session",
		filters={
			"status": "Active",
			"target_end_time": ["<", now_datetime()],
			"expiry_notified_at": ["is", "not set"],
		},
		fields=["name", "employee", "work_section", "target_end_time"],
	)
	for section in expired:
		if not is_tracking_enabled(section.employee):
			continue
		message = {
			"section_session": section.name,
			"employee": section.employee,
			"work_section": section.work_section,
			"target_end_time": section.target_end_time,
		}
		frappe.publish_realtime(
			event="mm_employee_watcher:section_expired",
			message=message,
			user=frappe.db.get_value("Employee", section.employee, "user_id"),
		)
		frappe.publish_realtime(
			event="mm_employee_watcher:dashboard_update",
			message={**message, "section_overdue": True},
		)
		frappe.db.set_value(
			"Employee Section Session",
			section.name,
			"expiry_notified_at",
			now_datetime(),
			update_modified=False,
		)


def notify_due_section_schedules():
	"""Push each due schedule once and mark missed unstarted entries skipped."""
	now = now_datetime()
	due = frappe.get_all(
		"Employee Section Schedule",
		filters={
			"status": "Scheduled",
			"scheduled_start": ["<=", now],
			"scheduled_end": [">", now],
			"start_notified_at": ["is", "not set"],
		},
		fields=[
			"name",
			"employee",
			"work_section",
			"default_work_activity",
			"scheduled_start",
			"scheduled_end",
			"notes",
		],
	)
	for schedule in due:
		if not is_tracking_enabled(schedule.employee):
			continue
		frappe.publish_realtime(
			event="mm_employee_watcher:section_required",
			message={
				"message": "Please start scheduled work",
				"next_schedule": schedule,
			},
			user=frappe.db.get_value("Employee", schedule.employee, "user_id"),
		)
		frappe.db.set_value(
			"Employee Section Schedule",
			schedule.name,
			"start_notified_at",
			now,
			update_modified=False,
		)

	missed = frappe.get_all(
		"Employee Section Schedule",
		filters={"status": "Scheduled", "scheduled_end": ["<=", now]},
		pluck="name",
	)
	for name in missed:
		frappe.db.set_value("Employee Section Schedule", name, "status", "Skipped")


def check_offline_employees():
	"""Employees whose last heartbeat is older than OFFLINE_AFTER_MINUTES,
	and who are not on an authorized BREAK or already OFFLINE/OFF DUTY,
	get flipped to OFFLINE rather than being silently counted as idle."""
	cutoff = offline_cutoff()

	stale = frappe.get_all(
		"Employee Current Status",
		filters={
			"status": ["in", [STATUS_WORKING, STATUS_IDLE, STATUS_BLOCKED]],
		},
		fields=["employee", "current_session", "last_heartbeat", "status_since"],
	)

	for row in stale:
		last_seen = row.last_heartbeat or row.status_since
		if not last_seen or get_datetime(last_seen) >= get_datetime(cutoff):
			continue
		if not is_tracking_enabled(row.employee):
			continue
		if row.current_session:
			log_event(row.employee, row.current_session, "Idle Start", remarks="no heartbeat")
		set_status(row.employee, STATUS_OFFLINE, None)
