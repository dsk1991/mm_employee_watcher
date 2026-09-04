"""Scheduled jobs registered in hooks.py.

check_expired_sessions   -> the "2:00 PM" flow: one-shot realtime alert for
                             each target time, every minute.
check_offline_employees  -> heartbeat watchdog: a dropped connection/closed
                             app becomes OFFLINE, never silently IDLE.
raise_supervisor_alerts  -> per-minute sweep that opens/clears Employee
                             Watcher Alert records (Idle / Overdue / Blocked)
                             and notifies the configured recipients.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime, time_diff_in_seconds

from mm_employee_watcher.utils import (
	STATUS_IDLE,
	STATUS_OFFLINE,
	STATUS_WORKING,
	STATUS_BLOCKED,
	SESSION_ACTIVE,
	SESSION_EXTENDED,
	SESSION_BLOCKED,
	set_status,
	is_tracking_enabled,
	log_event,
	offline_cutoff,
	get_watcher_settings,
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


# ---------------------------------------------------------------------------
# Supervisor alerts (Idle / Overdue / Blocked)
# ---------------------------------------------------------------------------

ALERT_LABEL = {
	"Idle": "idle with no active work",
	"Overdue": "past the target time",
	"Blocked": "blocked",
}


def _minutes_since(value, now):
	return time_diff_in_seconds(now, get_datetime(value)) / 60.0


def raise_supervisor_alerts():
	"""Per-minute sweep: open an Employee Watcher Alert (and notify the
	configured recipients) when an employee crosses an Idle / Overdue /
	Blocked threshold, and clear the alert once the condition is gone."""
	settings = get_watcher_settings()
	open_alerts = frappe.get_all(
		"Employee Watcher Alert",
		filters={"status": "Open"},
		fields=["name", "employee", "alert_type", "raised_at"],
	)
	open_keys = {(a.employee, a.alert_type): a for a in open_alerts}

	if not settings["alerts_enabled"] or not settings["recipients"]:
		now = now_datetime()
		for alert in open_keys.values():
			_close_alert(alert.name, now)
		return

	now = now_datetime()
	recipients = settings["recipients"]
	breaches = {}

	statuses = frappe.get_all(
		"Employee Current Status",
		filters={"status": ["in", [STATUS_IDLE, STATUS_WORKING, STATUS_BLOCKED]]},
		fields=["employee", "status", "status_since", "idle_since", "current_session"],
	)
	for row in statuses:
		if not is_tracking_enabled(row.employee):
			continue

		session = None
		if row.current_session:
			session = frappe.db.get_value(
				"Employee Work Session",
				row.current_session,
				["name", "status", "work_activity", "target_end_time", "blocked_reason"],
				as_dict=True,
			)

		if row.status == STATUS_IDLE and row.idle_since:
			if _minutes_since(row.idle_since, now) >= settings["idle_alert_minutes"]:
				breaches[(row.employee, "Idle")] = {
					"work_session": session.name if session else None,
					"work_activity": session.work_activity if session else None,
					"reason": None,
				}

		if session and session.status == SESSION_BLOCKED and row.status_since:
			if _minutes_since(row.status_since, now) >= settings["blocked_alert_minutes"]:
				breaches[(row.employee, "Blocked")] = {
					"work_session": session.name,
					"work_activity": session.work_activity,
					"reason": session.blocked_reason,
				}

		if (
			session
			and session.status in (SESSION_ACTIVE, SESSION_EXTENDED)
			and session.target_end_time
		):
			if _minutes_since(session.target_end_time, now) >= settings["overdue_alert_minutes"]:
				breaches[(row.employee, "Overdue")] = {
					"work_session": session.name,
					"work_activity": session.work_activity,
					"reason": None,
				}

	for key, info in breaches.items():
		if key in open_keys:
			continue
		employee, alert_type = key
		alert = frappe.get_doc(
			{
				"doctype": "Employee Watcher Alert",
				"employee": employee,
				"alert_type": alert_type,
				"status": "Open",
				"raised_at": now,
				"work_session": info["work_session"],
				"work_activity": info["work_activity"],
				"reason": info["reason"],
				"notified_users": ", ".join(recipients),
			}
		)
		alert.insert(ignore_permissions=True)
		_notify_alert(alert, recipients)

	for key, alert in open_keys.items():
		if key not in breaches:
			_close_alert(alert.name, now)


def _close_alert(name, now):
	doc = frappe.get_doc("Employee Watcher Alert", name)
	if doc.status == "Cleared":
		return
	doc.status = "Cleared"
	doc.cleared_at = now
	doc.open_minutes = int(max(0, time_diff_in_seconds(now, get_datetime(doc.raised_at)) // 60))
	doc.save(ignore_permissions=True)
	frappe.publish_realtime(event="mm_employee_watcher:dashboard_update", message={"alert_cleared": name})


def _notify_alert(alert, recipients):
	who = alert.get("employee_name") or alert.employee
	subject = _("{0} is {1}").format(who, _(ALERT_LABEL.get(alert.alert_type, alert.alert_type)))
	if alert.reason:
		subject += " — " + alert.reason

	for user in recipients:
		try:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": subject,
					"for_user": user,
					"from_user": "Administrator",
					"type": "Alert",
					"document_type": "Employee Watcher Alert",
					"document_name": alert.name,
				}
			).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title="MM Watcher alert notification failed", message=frappe.get_traceback()
			)
		frappe.publish_realtime(
			event="mm_employee_watcher:supervisor_alert",
			message={
				"alert": alert.name,
				"employee": alert.employee,
				"employee_name": who,
				"alert_type": alert.alert_type,
				"reason": alert.reason,
				"work_activity": alert.work_activity,
			},
			user=user,
		)
	frappe.publish_realtime(event="mm_employee_watcher:dashboard_update", message={"alert": alert.name})
