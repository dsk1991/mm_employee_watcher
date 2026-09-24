"""Pure time accounting for a work session (no Frappe imports, unit-testable).

A session's wall-clock span includes the times the employee was paused,
blocked or on a break; "working" time excludes them, and "waiting" is how long
the task sat in the queue before anyone started it.
"""

from __future__ import annotations

from datetime import datetime

PAUSE_EVENTS = {"Pause", "Blocked", "Break Start"}
RESUME_EVENTS = {"Resume", "Unblocked", "Break End"}
END_EVENTS = {"Complete", "Cancelled"}


def _seconds(later: datetime, earlier: datetime) -> float:
	return max(0.0, (later - earlier).total_seconds())


def compute_time_breakdown(events, start: datetime, end: datetime) -> dict[str, float]:
	"""`events` is an ASC-sorted iterable of (event_type, event_time). Returns
	{"total", "paused", "working"} in seconds between `start` and `end`; a
	pause still open at `end` counts up to `end`."""
	paused = 0.0
	paused_since = None
	for event_type, at in events:
		if at < start:
			continue
		if at > end:
			break
		if event_type in PAUSE_EVENTS and paused_since is None:
			paused_since = at
		elif (event_type in RESUME_EVENTS or event_type in END_EVENTS) and paused_since is not None:
			paused += _seconds(at, paused_since)
			paused_since = None
	if paused_since is not None:
		paused += _seconds(end, paused_since)
	total = _seconds(end, start)
	paused = min(paused, total)
	return {"total": total, "paused": paused, "working": total - paused}


def waiting_seconds(queued_at: datetime | None, started_at: datetime | None) -> float:
	"""How long a queue item waited before its session started."""
	if not queued_at or not started_at:
		return 0.0
	return _seconds(started_at, queued_at)


def pick_next(items, employee_zones=None):
	"""Choose the next pool item: highest priority, then the employee's own
	zones, then oldest. `items` are dicts with priority, zone, creation."""
	zones = {z.strip().lower() for z in (employee_zones or []) if z and z.strip()}

	def rank(item):
		in_zone = 1 if zones and (item.get("zone") or "").strip().lower() in zones else 0
		return (-(item.get("priority") or 0), -in_zone, item.get("creation"))

	return sorted(items, key=rank)[0] if items else None
