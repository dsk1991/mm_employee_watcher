"""Employee Work Report — worked / idle / break / blocked hours per employee
over a date range, plus how many work sessions and an average efficiency
(Work Activity standard duration vs actual)."""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, get_datetime, getdate, now_datetime, time_diff_in_seconds

from mm_employee_watcher.utils import pair_state_durations

ONGOING = ("Active", "Extended", "Paused", "Blocked")
MAX_RANGE_DAYS = 92


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.to_date or now_datetime())
	from_date = getdate(filters.from_date or add_days(to_date, -6))
	if date_diff(to_date, from_date) > MAX_RANGE_DAYS:
		frappe.throw(_("Please choose a date range of {0} days or fewer").format(MAX_RANGE_DAYS))
	start = f"{from_date} 00:00:00"
	end = f"{to_date} 23:59:59"
	now = now_datetime()
	cap = min(now, get_datetime(end))

	emp_filters = {"status": "Active"}
	if filters.employee:
		emp_filters["name"] = filters.employee
	if filters.department:
		emp_filters["department"] = filters.department
	employees = frappe.get_all(
		"Employee", filters=emp_filters, fields=["name", "employee_name", "department"]
	)
	emp_names = [e.name for e in employees]
	if not emp_names:
		return _columns(), []

	sessions = frappe.get_all(
		"Employee Work Session",
		filters={"employee": ["in", emp_names], "start_time": ["between", [start, end]]},
		fields=["employee", "status", "start_time", "actual_end_time", "work_activity"],
	)
	logs = frappe.get_all(
		"Employee Work Log",
		filters={"employee": ["in", emp_names], "event_time": ["between", [start, end]]},
		fields=["employee", "event_type", "event_time"],
		order_by="event_time asc",
	)
	standard = {
		a.name: flt(a.default_duration_minutes)
		for a in frappe.get_all(
			"Work Activity Master", fields=["name", "default_duration_minutes"]
		)
	}

	agg = {
		e.name: {"worked": 0.0, "idle": 0.0, "brk": 0.0, "blocked": 0.0, "sessions": 0, "eff_sum": 0.0, "eff_n": 0}
		for e in employees
	}

	for s in sessions:
		a = agg.get(s.employee)
		if not a:
			continue
		a["sessions"] += 1
		finish = s.actual_end_time or (now if s.status in ONGOING else None)
		if s.start_time and finish:
			secs = max(0, time_diff_in_seconds(finish, s.start_time))
			a["worked"] += secs
			std = standard.get(s.work_activity, 0)
			actual_min = secs / 60.0
			if std > 0 and actual_min > 0 and s.status == "Completed":
				a["eff_sum"] += min(300.0, std / actual_min * 100.0)
				a["eff_n"] += 1

	logs_by_emp = {}
	for row in logs:
		logs_by_emp.setdefault(row.employee, []).append(row)

	for emp, elogs in logs_by_emp.items():
		a = agg.get(emp)
		if not a:
			continue
		d = pair_state_durations(elogs, cap)
		a["idle"] += d["idle"]
		a["brk"] += d["break"]
		a["blocked"] += d["blocked"]

	data = []
	for e in employees:
		a = agg[e.name]
		if not (a["sessions"] or a["idle"] or a["brk"] or a["blocked"]):
			continue
		data.append(
			{
				"employee": e.name,
				"employee_name": e.employee_name,
				"department": e.department,
				"worked_hours": round(a["worked"] / 3600.0, 2),
				"idle_hours": round(a["idle"] / 3600.0, 2),
				"break_hours": round(a["brk"] / 3600.0, 2),
				"blocked_hours": round(a["blocked"] / 3600.0, 2),
				"sessions": a["sessions"],
				"efficiency": round(a["eff_sum"] / a["eff_n"], 0) if a["eff_n"] else None,
			}
		)

	data.sort(key=lambda r: -r["worked_hours"])
	return _columns(), data


def _columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 150},
		{"label": _("Worked (h)"), "fieldname": "worked_hours", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("Idle (h)"), "fieldname": "idle_hours", "fieldtype": "Float", "precision": 2, "width": 90},
		{"label": _("Break (h)"), "fieldname": "break_hours", "fieldtype": "Float", "precision": 2, "width": 90},
		{"label": _("Blocked (h)"), "fieldname": "blocked_hours", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("Sessions"), "fieldname": "sessions", "fieldtype": "Int", "width": 90},
		{"label": _("Avg Efficiency %"), "fieldname": "efficiency", "fieldtype": "Float", "precision": 0, "width": 120},
	]
