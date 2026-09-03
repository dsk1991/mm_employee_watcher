"""Whitelisted API surface.

Every client — ERPNext Desk header bar/popup, WMS, the Android HHT app —
talks to the watcher only through these methods, so all of them read/write
exactly the same state. See docs/backend-architecture.md section 5.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, flt, cint, get_datetime

from mm_employee_watcher.utils import (
	STATUS_WORKING,
	STATUS_IDLE,
	STATUS_BREAK,
	STATUS_BLOCKED,
	SESSION_ACTIVE,
	SESSION_EXTENDED,
	SESSION_PAUSED,
	SESSION_BLOCKED,
	SESSION_COMPLETED,
	SESSION_CANCELLED,
	get_active_session,
	get_or_create_status,
	get_employee_for_user,
	is_tracking_enabled,
	publish_status,
	set_status,
	log_event,
)

MANAGER_ROLES = {"System Manager", "Employee Watcher Manager"}
OPEN_SESSION_STATUSES = {SESSION_ACTIVE, SESSION_EXTENDED, SESSION_PAUSED, SESSION_BLOCKED}


def _has_manager_role():
	return bool(MANAGER_ROLES.intersection(frappe.get_roles()))


def _get_employee_for_user(employee=None):
	"""Resolve the acting Employee: an explicit employee (supervisor/HHT
	acting on someone's behalf) or the logged-in user's own Employee
	(requirement #2 — Employee master is linked to User via user_id, so a
	plain login is enough to know who this is). An ordinary employee may
	never use this argument to impersonate another employee."""
	acting_employee = get_employee_for_user()
	if employee:
		if employee == acting_employee:
			return employee
		if not _has_manager_role():
			frappe.throw(_("You cannot act on behalf of another employee"), frappe.PermissionError)
		if not frappe.db.exists("Employee", {"name": employee, "status": "Active"}):
			frappe.throw(_("Employee {0} is not active").format(employee))
		return employee
	if not acting_employee:
		frappe.throw(_("No active Employee record linked to this user"))
	return acting_employee


def _get_session_for_actor(work_session):
	"""Return a session only when the caller owns it or is a watcher manager."""
	session = frappe.get_doc("Employee Work Session", work_session)
	acting_employee = get_employee_for_user()
	if session.employee != acting_employee and not _has_manager_role():
		frappe.throw(_("You cannot change another employee's work session"), frappe.PermissionError)
	return session


def _require_session_status(session, allowed_statuses, action):
	if session.status not in allowed_statuses:
		frappe.throw(
			_("Cannot {0} a work session with status {1}").format(action, session.status)
		)


def _create_session(
	employee,
	work_activity,
	target_qty=None,
	minutes=None,
	reference_doctype=None,
	reference_name=None,
	source_app="ERPNext",
	description=None,
	queue_item=None,
):
	"""Shared by start_work() and the auto-chain in complete_work() — one
	code path for 'open a new Primary Active Work session'."""
	activity = frappe.get_doc("Work Activity Master", work_activity)
	if not frappe.has_permission("Work Activity Master", "read", doc=activity):
		frappe.throw(_("You do not have permission to use this work activity"), frappe.PermissionError)
	minutes = cint(minutes) if minutes is not None else cint(activity.default_duration_minutes) or 60
	if minutes <= 0:
		frappe.throw(_("Duration must be greater than zero minutes"))
	if target_qty is not None and flt(target_qty) < 0:
		frappe.throw(_("Target Qty cannot be negative"))
	if bool(reference_doctype) != bool(reference_name):
		frappe.throw(_("Reference DocType and Reference Name must be provided together"))
	if reference_doctype and not frappe.db.exists(reference_doctype, reference_name):
		frappe.throw(_("Referenced {0} {1} does not exist").format(reference_doctype, reference_name))
	if reference_doctype and not frappe.has_permission(reference_doctype, "read", doc=reference_name):
		frappe.throw(_("You do not have permission to use the referenced document"), frappe.PermissionError)

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
			"notes": description,
			"queue_item": queue_item,
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
	session = _create_session(
		employee,
		item.work_activity,
		target_qty=item.target_qty,
		reference_doctype=item.reference_doctype,
		reference_name=item.reference_name,
		queue_item=item.name,
	)
	frappe.db.set_value("Employee Work Queue", item.name, "status", "Assigned")
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
	description: str | None = None,
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
		description=description,
	)
	return session.as_dict()


@frappe.whitelist()
def start_reference_work(
	work_activity: str,
	reference_doctype: str,
	reference_name: str,
	target_qty: float | None = None,
	target_minutes: int | None = None,
	source_app: str = "WMS",
):
	"""Idempotent WMS/HHT start endpoint keyed by employee + reference.

	A repeated mobile tap returns the existing matching session instead of
	creating a duplicate. A different open primary session remains a hard
	conflict and must be completed or cancelled explicitly.
	"""
	employee = _get_employee_for_user()
	if not is_tracking_enabled(employee):
		return {"tracking": False, "created": False, "session": None}

	existing = get_active_session(employee)
	if existing:
		if (
			existing.work_activity == work_activity
			and existing.reference_doctype == reference_doctype
			and existing.reference_name == reference_name
		):
			return {"tracking": True, "created": False, "session": existing.as_dict()}

	completed = frappe.get_all(
		"Employee Work Session",
		filters={
			"employee": employee,
			"work_activity": work_activity,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": SESSION_COMPLETED,
		},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)
	if completed:
		return {
			"tracking": True,
			"created": False,
			"completed": True,
			"session": frappe.get_doc("Employee Work Session", completed[0].name).as_dict(),
		}
	if existing:
		frappe.throw(
			_("You already have active work {0} ({1}). Finish it before starting {2}.").format(
				existing.work_activity, existing.name, reference_name
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
	return {"tracking": True, "created": True, "session": session.as_dict()}


def _complete_session(session, completed_qty=None, remarks=None):
	if session.status == SESSION_COMPLETED:
		return {"already_completed": True, "auto_started": None, "next_work": None}
	_require_session_status(session, OPEN_SESSION_STATUSES, _("complete"))

	session.status = SESSION_COMPLETED
	session.actual_end_time = now_datetime()
	if completed_qty is not None:
		completed_qty = flt(completed_qty)
		if completed_qty < 0:
			frappe.throw(_("Completed Qty cannot be negative"))
		session.completed_qty = completed_qty
	if remarks:
		session.notes = remarks
	session.save(ignore_permissions=True)

	if session.queue_item and frappe.db.exists("Employee Work Queue", session.queue_item):
		frappe.db.set_value("Employee Work Queue", session.queue_item, "status", "Completed")

	log_event(session.employee, session.name, "Complete", qty=session.completed_qty, remarks=remarks)

	auto_started = None
	auto_start_failed = False
	if is_tracking_enabled(session.employee):
		savepoint = "mm_employee_watcher_auto_chain"
		frappe.db.savepoint(savepoint)
		try:
			auto_started = _start_next_from_queue(session.employee)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			auto_start_failed = True
			frappe.log_error(
				title="MM Employee Watcher auto-chain failed",
				message=frappe.get_traceback(),
			)

	if not auto_started:
		set_status(session.employee, STATUS_IDLE, None)

	return {
		"already_completed": False,
		"auto_started": auto_started,
		"auto_start_failed": auto_start_failed,
		"next_work": None if auto_started else get_next_work(session.employee),
	}


@frappe.whitelist()
def complete_work(work_session: str, completed_qty: float | None = None, remarks: str | None = None):
	"""Employee taps Done (or an integration hook calls this automatically
	when the source WMS/production document finishes). Requirement #5:
	immediately tries to auto-start the next queued work for this
	employee; only falls back to IDLE if the queue is empty."""
	return _complete_session(_get_session_for_actor(work_session), completed_qty, remarks)


@frappe.whitelist()
def complete_reference_work(
	reference_doctype: str,
	reference_name: str,
	completed_qty: float | None = None,
	remarks: str | None = None,
):
	"""Idempotently complete the caller's open WMS/HHT reference session."""
	employee = _get_employee_for_user()
	rows = frappe.get_all(
		"Employee Work Session",
		filters={
			"employee": employee,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": ["in", list(OPEN_SESSION_STATUSES)],
		},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		completed = frappe.get_all(
			"Employee Work Session",
			filters={
				"employee": employee,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"status": SESSION_COMPLETED,
			},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		if completed:
			return {"already_completed": True, "work_session": completed[0].name}
		frappe.throw(_("No open work session found for {0} {1}").format(reference_doctype, reference_name))
	result = _complete_session(frappe.get_doc("Employee Work Session", rows[0].name), completed_qty, remarks)
	result["work_session"] = rows[0].name
	return result


@frappe.whitelist()
def update_progress(work_session: str, completed_qty: float):
	"""Update live progress from WMS without allowing cross-employee writes."""
	session = _get_session_for_actor(work_session)
	_require_session_status(session, OPEN_SESSION_STATUSES, _("update"))
	completed_qty = flt(completed_qty)
	if completed_qty < 0:
		frappe.throw(_("Completed Qty cannot be negative"))
	session.completed_qty = completed_qty
	session.save(ignore_permissions=True)
	publish_status(session.employee)
	return {"ok": True, "completed_qty": session.completed_qty}


@frappe.whitelist()
def extend_work(work_session: str, minutes: int):
	"""Extend the current target_end_time by 15 / 30 / 60 / custom minutes."""
	minutes = cint(minutes)
	if minutes <= 0:
		frappe.throw(_("Extension must be greater than zero minutes"))
	session = _get_session_for_actor(work_session)
	_require_session_status(session, {SESSION_ACTIVE, SESSION_EXTENDED}, _("extend"))
	session.target_end_time = add_to_date(session.target_end_time, minutes=minutes)
	session.extended_minutes = cint(session.extended_minutes) + minutes
	session.status = SESSION_EXTENDED
	session.expiry_notified_at = None
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Extend", remarks=f"+{minutes} min")
	set_status(session.employee, STATUS_WORKING, session.name)
	return session.as_dict()


@frappe.whitelist()
def pause_work(work_session: str, reason: str | None = None):
	session = _get_session_for_actor(work_session)
	_require_session_status(session, {SESSION_ACTIVE, SESSION_EXTENDED}, _("pause"))
	session.status = SESSION_PAUSED
	session.save(ignore_permissions=True)
	log_event(session.employee, session.name, "Pause", remarks=reason)
	set_status(session.employee, STATUS_IDLE, session.name)
	return {"ok": True}


@frappe.whitelist()
def resume_work(work_session: str):
	session = _get_session_for_actor(work_session)
	_require_session_status(session, {SESSION_PAUSED, SESSION_BLOCKED}, _("resume"))
	was_blocked = session.status == SESSION_BLOCKED
	session.status = SESSION_ACTIVE
	session.blocked_reason = None
	session.save(ignore_permissions=True)
	log_event(session.employee, session.name, "Unblocked" if was_blocked else "Resume")
	set_status(session.employee, STATUS_WORKING, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_blocked(work_session: str, reason: str):
	if not (reason or "").strip():
		frappe.throw(_("Blocked reason is required"))
	session = _get_session_for_actor(work_session)
	_require_session_status(
		session, {SESSION_ACTIVE, SESSION_EXTENDED, SESSION_PAUSED}, _("block")
	)
	session.status = SESSION_BLOCKED
	session.blocked_reason = reason.strip()
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Blocked", remarks=reason)
	set_status(session.employee, STATUS_BLOCKED, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_break(employee: str | None = None, reason: str | None = None):
	"""Authorized lunch/tea break — a distinct state from IDLE."""
	employee = _get_employee_for_user(employee)
	session = get_active_session(employee)
	if session and session.status in {SESSION_ACTIVE, SESSION_EXTENDED}:
		session.status = SESSION_PAUSED
		session.save(ignore_permissions=True)
		log_event(employee, session.name, "Pause", remarks=reason or _("Authorized break"))
	elif session and session.status == SESSION_BLOCKED:
		frappe.throw(_("Resolve or complete the blocked work before starting a break"))
	set_status(employee, STATUS_BREAK, session.name if session else None)
	return {"ok": True}


def _record_heartbeat(employee):
	status = get_or_create_status(employee)
	status.db_set("last_heartbeat", now_datetime(), update_modified=False)
	if status.status != "OFFLINE":
		return status

	session = get_active_session(employee)
	if session and session.status == SESSION_BLOCKED:
		return set_status(employee, STATUS_BLOCKED, session.name)
	if session and session.status == SESSION_PAUSED:
		return set_status(employee, STATUS_IDLE, session.name)
	if session:
		return set_status(employee, STATUS_WORKING, session.name)
	return set_status(employee, STATUS_IDLE, None)


@frappe.whitelist()
def get_my_status(employee: str | None = None):
	"""What the Desk popup / Smart Work Bar reads on load. Returns
	employee: None when this user has no linked Employee, or tracking: 0
	when tracking is off for them — the caller should stay silent then."""
	employee = _get_employee_for_user(employee) if employee else get_employee_for_user()
	if not employee:
		return {"employee": None}

	tracking = is_tracking_enabled(employee)
	if not tracking:
		return {"employee": employee, "tracking": False}
	status_doc = _record_heartbeat(employee)
	status = {
		"status": status_doc.status,
		"current_session": status_doc.current_session,
		"status_since": status_doc.status_since,
	}

	result = {"employee": employee, "tracking": tracking, **status}
	if status["current_session"]:
		session = frappe.get_doc("Employee Work Session", status["current_session"])
		result["session"] = session.as_dict()
		result["expired"] = bool(
			session.status in {SESSION_ACTIVE, SESSION_EXTENDED}
			and session.target_end_time
			and get_datetime(session.target_end_time) < now_datetime()
		)
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
	if not is_tracking_enabled(employee):
		return {"ok": True, "tracking": False, "server_time": now_datetime()}
	_record_heartbeat(employee)
	return {"ok": True, "tracking": True, "server_time": now_datetime()}
