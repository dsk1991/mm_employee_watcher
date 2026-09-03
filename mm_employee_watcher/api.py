"""Whitelisted API surface.

Every client — ERPNext Desk header bar/popup, WMS, the Android HHT app —
talks to the watcher only through these methods, so all of them read/write
exactly the same state. See docs/backend-architecture.md section 5.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, flt, cint

from mm_employee_watcher.utils import (
	STATUS_WORKING,
	STATUS_IDLE,
	STATUS_BREAK,
	STATUS_BLOCKED,
	SESSION_ACTIVE,
	SESSION_EXTENDED,
	SESSION_BLOCKED,
	SESSION_COMPLETED,
	SESSION_CANCELLED,
	get_active_session,
	get_or_create_status,
	get_employee_for_user,
	is_tracking_enabled,
	set_status,
	log_event,
)


def _get_employee_for_user(employee=None):
	"""Resolve the acting Employee: an explicit employee (supervisor/HHT
	acting on someone's behalf) or the logged-in user's own Employee
	(requirement #2 — Employee master is linked to User via user_id, so a
	plain login is enough to know who this is)."""
	if employee:
		return employee
	employee = get_employee_for_user()
	if not employee:
		frappe.throw(_("No active Employee record linked to this user"))
	return employee


def _create_session(
	employee,
	work_activity,
	target_qty=None,
	minutes=None,
	reference_doctype=None,
	reference_name=None,
	source_app="ERPNext",
):
	"""Shared by start_work() and the auto-chain in complete_work() — one
	code path for 'open a new Primary Active Work session'."""
	activity = frappe.get_doc("Work Activity Master", work_activity)
	minutes = cint(minutes) or cint(activity.default_duration_minutes) or 60

	session = frappe.get_doc(
		{
			"doctype": "Employee Work Session",
			"employee": employee,
			"work_activity": work_activity,
			"source_app": source_app,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": SESSION_ACTIVE,
			"is_primary": 1,
			"start_time": now_datetime(),
			"target_end_time": add_to_date(now_datetime(), minutes=minutes),
			"target_qty": target_qty,
			"completed_qty": 0,
		}
	)
	session.insert(ignore_permissions=True)

	log_event(employee, session.name, "Start")
	set_status(employee, STATUS_WORKING, session.name)
	return session


def _start_next_from_queue(employee):
	"""Requirement #5: as soon as one work is done, pick up the next
	queued item automatically — no idle gap, no manual Start tap. Returns
	the new Employee Work Session dict, or None if the queue is empty (the
	employee goes IDLE and the Desk 'Work Now' popup takes over)."""
	next_item = frappe.get_all(
		"Employee Work Queue",
		filters={"employee": employee, "status": "Pending"},
		fields=["name", "work_activity", "reference_doctype", "reference_name", "target_qty"],
		order_by="priority desc, creation asc",
		limit=1,
	)
	if not next_item:
		return None

	item = next_item[0]
	frappe.db.set_value("Employee Work Queue", item.name, "status", "Assigned")

	session = _create_session(
		employee,
		item.work_activity,
		target_qty=item.target_qty,
		reference_doctype=item.reference_doctype,
		reference_name=item.reference_name,
	)
	return session.as_dict()


@frappe.whitelist()
def start_work(
	work_activity: str,
	employee: str | None = None,
	target_qty: float | None = None,
	target_minutes: int | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	source_app: str = "ERPNext",
):
	"""Start a new Primary Active Work session — from the Desk 'Work Now'
	popup, WMS, or the HHT app. Refuses if the employee already has one
	open (the DocType also validates this server-side)."""
	employee = _get_employee_for_user(employee)

	if not is_tracking_enabled(employee):
		frappe.throw(_("Work tracking is disabled for this user"))

	existing = get_active_session(employee)
	if existing:
		frappe.throw(
			_("{0} already has an active session ({1}). Complete, extend or block it first.").format(
				employee, existing.name
			)
		)

	session = _create_session(
		employee,
		work_activity,
		target_qty=target_qty,
		minutes=target_minutes,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		source_app=source_app,
	)
	return session.as_dict()


@frappe.whitelist()
def complete_work(work_session: str, completed_qty: float | None = None, remarks: str | None = None):
	"""Employee taps Done (or an integration hook calls this automatically
	when the source WMS/production document finishes). Requirement #5:
	immediately tries to auto-start the next queued work for this
	employee; only falls back to IDLE if the queue is empty."""
	session = frappe.get_doc("Employee Work Session", work_session)
	session.status = SESSION_COMPLETED
	session.actual_end_time = now_datetime()
	if completed_qty is not None:
		session.completed_qty = flt(completed_qty)
	if remarks:
		session.notes = remarks
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Complete", qty=session.completed_qty, remarks=remarks)

	auto_started = None
	if is_tracking_enabled(session.employee):
		auto_started = _start_next_from_queue(session.employee)

	if not auto_started:
		set_status(session.employee, STATUS_IDLE, None)

	return {
		"auto_started": auto_started,
		"next_work": None if auto_started else get_next_work(session.employee),
	}


@frappe.whitelist()
def extend_work(work_session: str, minutes: int):
	"""Extend the current target_end_time by 15 / 30 / 60 / custom minutes."""
	minutes = cint(minutes)
	session = frappe.get_doc("Employee Work Session", work_session)
	session.target_end_time = add_to_date(session.target_end_time, minutes=minutes)
	session.extended_minutes = cint(session.extended_minutes) + minutes
	session.status = SESSION_EXTENDED
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Extend", remarks=f"+{minutes} min")
	set_status(session.employee, STATUS_WORKING, session.name)
	return session.as_dict()


@frappe.whitelist()
def pause_work(work_session: str, reason: str | None = None):
	session = frappe.get_doc("Employee Work Session", work_session)
	log_event(session.employee, session.name, "Pause", remarks=reason)
	set_status(session.employee, STATUS_IDLE, session.name)
	return {"ok": True}


@frappe.whitelist()
def resume_work(work_session: str):
	session = frappe.get_doc("Employee Work Session", work_session)
	log_event(session.employee, session.name, "Resume")
	set_status(session.employee, STATUS_WORKING, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_blocked(work_session: str, reason: str):
	session = frappe.get_doc("Employee Work Session", work_session)
	session.status = SESSION_BLOCKED
	session.blocked_reason = reason
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Blocked", remarks=reason)
	set_status(session.employee, STATUS_BLOCKED, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_break(employee: str | None = None, reason: str | None = None):
	"""Authorized lunch/tea break — a distinct state from IDLE."""
	employee = _get_employee_for_user(employee)
	set_status(employee, STATUS_BREAK, None)
	return {"ok": True}


@frappe.whitelist()
def get_my_status(employee: str | None = None):
	"""What the Desk popup / Smart Work Bar reads on load. Returns
	employee: None when this user has no linked Employee, or tracking: 0
	when tracking is off for them — the caller should stay silent then."""
	employee = employee or get_employee_for_user()
	if not employee:
		return {"employee": None}

	tracking = is_tracking_enabled(employee)
	status = frappe.db.get_value(
		"Employee Current Status",
		{"employee": employee},
		["status", "current_session", "status_since"],
		as_dict=True,
	)
	if not status:
		return {"employee": employee, "tracking": tracking, "status": "OFFLINE", "current_session": None}

	result = {"employee": employee, "tracking": tracking, **status}
	if status.current_session:
		result["session"] = frappe.get_doc("Employee Work Session", status.current_session).as_dict()
	return result


@frappe.whitelist()
def get_next_work(employee: str | None = None):
	"""Next Employee Work Queue item for this employee, by priority — used
	both by the 'next priority work' prompt and the Desk 'Work Now' popup."""
	employee = _get_employee_for_user(employee)
	next_item = frappe.get_all(
		"Employee Work Queue",
		filters={"employee": employee, "status": "Pending"},
		fields=["name", "work_activity", "reference_doctype", "reference_name", "target_qty", "priority"],
		order_by="priority desc, creation asc",
		limit=1,
	)
	return next_item[0] if next_item else None


@frappe.whitelist()
def heartbeat(employee: str | None = None):
	"""Called periodically by every connected client so the offline
	watchdog can tell a genuinely idle employee from a dropped connection."""
	employee = _get_employee_for_user(employee)
	status = get_or_create_status(employee)
	status.db_set("last_heartbeat", now_datetime(), update_modified=False)
	return {"ok": True, "server_time": now_datetime()}
