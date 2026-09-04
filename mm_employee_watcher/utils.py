"""Shared helpers used by api.py and tasks.py.

Kept small and dependency-free (only frappe) so both the whitelisted API
layer and the scheduled jobs share exactly one code path for status
transitions and realtime notifications.
"""

import frappe
from frappe.utils import now_datetime, add_to_date, cint

from mm_employee_watcher.state_machine import (
	OPEN_SESSION_STATUSES,
	SESSION_ACTIVE,
	SESSION_BLOCKED,
	SESSION_CANCELLED,
	SESSION_COMPLETED,
	SESSION_EXTENDED,
	SESSION_PAUSED,
)

TRACKING_FIELD = "mm_tracking_enabled"

STATUS_WORKING = "WORKING"
STATUS_IDLE = "IDLE"
STATUS_BREAK = "BREAK"
STATUS_BLOCKED = "BLOCKED"
STATUS_OFFLINE = "OFFLINE"
STATUS_OFF_DUTY = "OFF DUTY"

# Heartbeat older than this = employee counted OFFLINE, not IDLE.
OFFLINE_AFTER_MINUTES = 10

_UNSET = object()


def get_or_create_status(employee: str):
	"""Return the singleton Employee Current Status row for an employee,
	creating an OFFLINE one if this employee has never had one before."""
	name = frappe.db.exists("Employee Current Status", {"employee": employee})
	if name:
		return frappe.get_doc("Employee Current Status", name)

	doc = frappe.new_doc("Employee Current Status")
	doc.employee = employee
	doc.status = STATUS_OFFLINE
	doc.status_since = now_datetime()
	doc.insert(ignore_permissions=True)
	return doc


def set_status(employee: str, status: str, current_session: str | None = None):
	"""Central place that changes Employee Current Status and notifies
	every connected client via realtime — this is what the floating work
	widget in every app listens to."""
	doc = get_or_create_status(employee)
	changed = doc.status != status or doc.current_session != current_session
	if doc.status == STATUS_BREAK and status != STATUS_BREAK:
		log_event(employee, current_session or doc.current_session, "Break End")
	if status != STATUS_BREAK:
		doc.break_until = None
	doc.status = status
	doc.current_session = current_session
	doc.status_since = now_datetime() if changed or not doc.status_since else doc.status_since
	if status == STATUS_IDLE and (changed or not doc.idle_since):
		doc.idle_since = now_datetime()
	else:
		if status != STATUS_IDLE:
			doc.idle_since = None
	doc.save(ignore_permissions=True)

	publish_status(employee, doc)
	return doc


def publish_status(employee: str, status_doc=None):
	"""Push the employee's current work state to every connected client
	(Desk, WMS, HHT) via Socket.IO. Closed/backgrounded mobile apps won't
	receive this — see docs/backend-architecture.md section 8 (FCM)."""
	if status_doc is None:
		status_doc = get_or_create_status(employee)

	payload = {
		"employee": employee,
		"status": status_doc.status,
		"current_session": status_doc.current_session,
		"status_since": status_doc.status_since,
	}

	# Session-specific detail for the floating work widget, if one is active.
	if status_doc.current_session:
		session = frappe.db.get_value(
			"Employee Work Session",
			status_doc.current_session,
			[
				"work_activity",
				"target_qty",
				"completed_qty",
				"target_end_time",
				"reference_doctype",
				"reference_name",
			],
			as_dict=True,
		)
		if session:
			payload.update(session)

	frappe.publish_realtime(
		event="mm_employee_watcher:status_update",
		message=payload,
		user=frappe.db.get_value("Employee", employee, "user_id"),
	)
	# Also broadcast to the supervisor dashboard room.
	frappe.publish_realtime(
		event="mm_employee_watcher:dashboard_update",
		message=payload,
	)


def get_active_session(employee: str):
	"""The employee's current Primary Active Work, if any. Enforces the
	'one primary active session at a time' rule by construction: callers
	must go through start_work() / complete this session first."""
	name = frappe.db.exists(
		"Employee Work Session",
		{
			"employee": employee,
			"is_primary": 1,
			"status": ["in", list(OPEN_SESSION_STATUSES)],
		},
	)
	return frappe.get_doc("Employee Work Session", name) if name else None


def log_event(
	employee,
	work_session,
	event_type,
	qty=None,
	remarks=None,
	source_app=None,
	reference_doctype=None,
	reference_name=None,
):
	doc = {
			"doctype": "Employee Work Log",
			"employee": employee,
			"work_session": work_session,
			"source_app": source_app,
			"event_type": event_type,
			"event_time": now_datetime(),
			"qty": qty,
			"remarks": remarks,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	frappe.get_doc(doc).insert(ignore_permissions=True)


def offline_cutoff():
	return add_to_date(now_datetime(), minutes=-OFFLINE_AFTER_MINUTES)


def get_user_for_employee(employee: str):
	return frappe.db.get_value("Employee", employee, "user_id")


def is_tracking_enabled(employee: str) -> bool:
	"""Requirement #4: a per-user on/off switch (Custom Field on User,
	created in install.py). Missing field or unset value defaults to
	tracked, so this is opt-out, not opt-in — matches 'by default track
	everyone, uncheck the ones who shouldn't be'."""
	user = get_user_for_employee(employee)
	if not user:
		return True
	if not frappe.db.has_column("User", TRACKING_FIELD):
		return True
	value = frappe.db.get_value("User", user, TRACKING_FIELD)
	if value is None:
		return True
	return bool(cint(value))


def get_employee_for_user(user: str | None = None):
	"""Requirement #2: resolve the Employee linked to a User via
	Employee.user_id — this is how the watcher knows 'who is logged in'
	without the employee having to pick themselves from a list."""
	user = user or frappe.session.user
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"})


ALERT_DEFAULTS = {
	"alerts_enabled": 1,
	"idle_alert_minutes": 15,
	"overdue_alert_minutes": 30,
	"blocked_alert_minutes": 20,
}


def get_watcher_settings():
	"""MM Watcher Settings as a plain dict, with defaults applied and the
	recipient user list resolved. Safe to call before the Single exists."""
	try:
		doc = frappe.get_cached_doc("MM Watcher Settings")
	except Exception:
		doc = None

	out = dict(ALERT_DEFAULTS)
	recipients = []
	if doc:
		for key in ALERT_DEFAULTS:
			value = doc.get(key)
			if value not in (None, ""):
				out[key] = cint(value) if key != "alerts_enabled" else bool(cint(value))
		recipients = [row.user for row in (doc.get("alert_recipients") or []) if row.user]
	out["alerts_enabled"] = bool(cint(out["alerts_enabled"]))
	out["recipients"] = [
		u for u in recipients if frappe.db.get_value("User", u, "enabled")
	]
	return out
