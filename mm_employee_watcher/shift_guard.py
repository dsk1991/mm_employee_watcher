"""Keep attendance and the work timer inside the employee's HRMS shift.

Runs every 5 minutes (hooks.scheduler_events) and on Punch In:

* Forgotten Punch Out - a Punch In whose shift has ended (shift end + the Shift
  Type's "allow check-out after shift end" minutes) gets an automatic Punch
  Out stamped at the shift end time, mirrored to HRMS Employee Checkin.
* Shift closed - when the employee is off duty (duty_state), the running work
  section is parked. The Pause is dated at the shift end, so time after the
  shift is not counted as work. Status becomes OFF DUTY.
* Shift started - once on duty again (inside the shift, or punched in), the
  section that was parked by the shift close is resumed automatically.

Employees without a shift are left alone (no shift = always on duty).
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from mm_employee_watcher import sections, timing
from mm_employee_watcher.state_machine import SESSION_ACTIVE, SESSION_EXTENDED, SESSION_PAUSED
from mm_employee_watcher.utils import (
	PUNCH_STALE_HOURS,
	STATUS_OFF_DUTY,
	STATUS_OFFLINE,
	duty_state,
	get_active_session,
	get_or_create_status,
	get_work_shift,
	is_tracking_enabled,
	last_punch,
	set_status,
)

AUTO_PAUSE_REMARK = "Shift closed (auto pause)"
AUTO_RESUME_WITHIN_HOURS = 36  # never revive a section parked longer ago than this


def _notify(employee, message):
	user = frappe.db.get_value("Employee", employee, "user_id")
	if user:
		frappe.publish_realtime(event="mm_employee_watcher:work_required", message={"message": message}, user=user)


def auto_punch_out(employee, now=None):
	"""Punch Out at the shift end for a Punch In the employee forgot to close.
	Returns the punch-out datetime, or None."""
	now = now or now_datetime()
	punch = last_punch(employee)
	if not punch or punch.log_type != "IN":
		return None
	punch_time = get_datetime(punch.punch_time)
	shift = get_work_shift(employee, punch_time)
	if not shift:
		return None
	end_dt = timing.shift_end_for(shift.start_time, shift.end_time, punch_time, cint(shift.allow_check_out_after_shift_end_time))
	if end_dt:
		deadline = end_dt + timedelta(minutes=cint(shift.allow_check_out_after_shift_end_time))
		out_time = end_dt
	else:  # punched in after the shift ended (overtime): close it once it is clearly forgotten
		deadline = add_to_date(punch_time, hours=PUNCH_STALE_HOURS)
		out_time = deadline
	if now < deadline:
		return None
	out_time = max(out_time, punch_time + timedelta(seconds=1))
	doc = frappe.get_doc({
		"doctype": "Employee Punch",
		"employee": employee,
		"log_type": "OUT",
		"punch_time": out_time,
		"shift": shift.name,
		"source": "Auto",
		"note": _("Auto Punch Out - shift {0} khatam (Punch Out bhool gaye)").format(shift.name),
	}).insert(ignore_permissions=True)
	from mm_employee_watcher.api import _mirror_to_hrms_checkin

	_mirror_to_hrms_checkin(doc)
	_notify(employee, _("Shift khatam: aapka Punch Out apne aap {0} par lag gaya").format(out_time.strftime("%H:%M")))
	return out_time


def _backdate_pause(session, pause_at):
	"""Move the Pause just logged by park_session back to the shift end, so the
	minutes after the shift are paused time, not work."""
	rows = frappe.get_all(
		"Employee Work Log",
		filters={"work_session": session.name},
		fields=["name", "event_type", "event_time", "remarks"],
		order_by="event_time desc, creation desc",
		limit=2,
	)
	if not rows or rows[0].event_type != "Pause" or rows[0].remarks != AUTO_PAUSE_REMARK:
		return
	floor = get_datetime(rows[1].event_time) if len(rows) > 1 else get_datetime(session.start_time)
	# Never move the pause before the last real event (that time was genuinely worked).
	if floor < pause_at < get_datetime(rows[0].event_time):
		frappe.db.set_value("Employee Work Log", rows[0].name, "event_time", pause_at, update_modified=False)


def pause_for_shift_end(employee, now=None, pause_at=None):
	"""Off duty: park the running section (Pause dated at the shift end) and mark OFF DUTY."""
	now = now or now_datetime()
	duty = duty_state(employee, now)
	if duty["on_duty"]:
		return None
	current = get_active_session(employee)
	parked = None
	if current and current.status in (SESSION_ACTIVE, SESSION_EXTENDED):
		sections.park_session(current, AUTO_PAUSE_REMARK)
		if not pause_at and duty.get("reason") == "off_shift":
			shift = get_work_shift(employee, now)
			pause_at = timing.last_shift_end(shift.end_time, now) if shift else None
		if pause_at and pause_at < now:
			_backdate_pause(current, pause_at)
		parked = current.name
		_notify(employee, _("Shift khatam: {0} ka timer ruk gaya, shift shuru hote hi wapas chalega").format(
			current.reference_name or current.work_activity))
	if get_or_create_status(employee).status != STATUS_OFF_DUTY:
		set_status(employee, STATUS_OFF_DUTY, None)
	return parked


def _auto_parked_section(employee, now):
	"""Latest section parked by the shift close (last log = our auto Pause)."""
	since = add_to_date(now, hours=-AUTO_RESUME_WITHIN_HOURS)
	for row in sections.parked_sessions(employee):
		last = frappe.get_all(
			"Employee Work Log",
			filters={"work_session": row.name},
			fields=["event_type", "event_time", "remarks"],
			order_by="event_time desc, creation desc",
			limit=1,
		)
		if not last:
			continue
		if last[0].event_type == "Pause" and last[0].remarks == AUTO_PAUSE_REMARK and get_datetime(last[0].event_time) >= since:
			return frappe.get_doc("Employee Work Session", row.name)
	return None


def resume_for_shift_start(employee, now=None):
	"""Back on duty (shift started, or punched in): resume the section the shift close parked."""
	now = now or now_datetime()
	duty = duty_state(employee, now)
	if not duty["on_duty"] or get_active_session(employee):
		return None
	shift = get_work_shift(employee, now)
	# Early check-in grace alone is not "shift started": wait for the shift start unless punched in.
	if shift and not duty["punched_in"] and not timing.in_shift_window(now, shift.start_time, shift.end_time, 0, (), 0):
		return None
	session = _auto_parked_section(employee, now)
	if not session or session.status != SESSION_PAUSED or (
		session.reference_doctype and sections.find_other_worker(session.reference_doctype, session.reference_name, employee)
	):
		# Nothing to resume: leave OFF DUTY so the next app heartbeat marks them IDLE.
		if shift and get_or_create_status(employee).status == STATUS_OFF_DUTY:
			set_status(employee, STATUS_OFFLINE, None)
		return None
	sections.unpark_session(session)
	_notify(employee, _("Shift shuru: {0} ka timer wapas chalu ho gaya").format(session.reference_name or session.work_activity))
	return session.name


def _employees_to_check():
	names = set(frappe.get_all("Employee Current Status", pluck="employee"))
	names.update(frappe.db.sql_list(
		"""select distinct employee from `tabEmployee Punch` where punch_time >= %s""",
		add_to_date(now_datetime(), days=-2),
	))
	return sorted(name for name in names if name)


def enforce_shifts():
	"""Scheduler entry point (every 5 minutes)."""
	now = now_datetime()
	for employee in _employees_to_check():
		try:
			frappe.db.savepoint("mm_shift_guard")
			out_time = auto_punch_out(employee, now)
			if is_tracking_enabled(employee):
				pause_for_shift_end(employee, now, pause_at=out_time)
				resume_for_shift_start(employee, now)
		except Exception:
			frappe.db.rollback(save_point="mm_shift_guard")
			frappe.log_error(title="MM Employee Watcher shift guard failed ({0})".format(employee), message=frappe.get_traceback())
