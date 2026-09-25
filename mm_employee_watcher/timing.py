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


def build_suggestions(stats):
	"""Plain-language tips for a worker from their own numbers (no Frappe).
	`stats` keys used (all optional): status, idle_minutes, assigned_count,
	top_assigned, pool_count, today_sessions, today_working_min,
	today_paused_min, period_sessions, on_time_pct, avg_working_min."""
	tips = []
	status = stats.get("status")
	idle = stats.get("idle_minutes") or 0
	assigned = stats.get("assigned_count") or 0
	pool = stats.get("pool_count") or 0

	if status == "IDLE":
		if assigned:
			top = stats.get("top_assigned") or "assigned kaam"
			tips.append({"type": "warn", "text": f"Aap {int(idle)} min se idle hain. Aapke paas {assigned} kaam assigned hai - '{top}' se shuru karein."})
		elif pool:
			tips.append({"type": "warn", "text": f"Aap {int(idle)} min se idle hain. Pool mein {pool} task waiting hain - NEXT TASK dabayein."})
		elif idle >= 15:
			tips.append({"type": "info", "text": f"Aap {int(idle)} min se idle hain aur koi task waiting nahi hai. Supervisor se naya kaam maangein."})
	elif assigned:
		tips.append({"type": "info", "text": f"Is kaam ke baad {assigned} aur kaam aapke queue mein hain."})

	paused = stats.get("today_paused_min") or 0
	working = stats.get("today_working_min") or 0
	total = paused + working
	if total >= 60 and paused / total > 0.25:
		tips.append({"type": "warn", "text": f"Aaj {int(100 * paused / total)}% samay pause/break/blocked mein gaya. Blocked reason clear karke kaam jaldi resume karein."})

	on_time = stats.get("on_time_pct")
	if on_time is not None and on_time < 70:
		tips.append({"type": "warn", "text": f"Sirf {int(on_time)}% kaam target time ke andar hua. Start karte waqt zyada time (+15m) rakhein ya bade kaam ko todkar karein."})
	elif on_time is not None and on_time >= 90 and (stats.get("period_sessions") or 0) >= 5:
		tips.append({"type": "good", "text": f"Shabash! {int(on_time)}% kaam target time par hua."})

	if (stats.get("today_sessions") or 0) == 0 and status != "IDLE" and working < 5:
		tips.append({"type": "info", "text": "Aaj abhi tak koi kaam complete nahi hua. Chhota kaam pehle khatam karke rhythm banayein."})
	if not tips:
		tips.append({"type": "good", "text": "Sab theek chal raha hai. Kaam ke end par batana na bhoolein ki kya kiya."})
	return tips


def haversine_m(lat1, lon1, lat2, lon2):
	"""Great-circle distance in metres between two GPS points."""
	from math import asin, cos, radians, sin, sqrt

	r = 6371000.0
	p1, p2 = radians(lat1), radians(lat2)
	dp, dl = p2 - p1, radians(lon2 - lon1)
	a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
	return 2 * r * asin(sqrt(a))


def _minutes(value):
	"""Minutes since midnight of a datetime.time / timedelta / 'HH:MM[:SS]'."""
	if hasattr(value, "total_seconds"):
		return int(value.total_seconds() // 60) % 1440
	if hasattr(value, "hour"):
		return value.hour * 60 + value.minute
	parts = str(value).split(":")
	return int(parts[0]) * 60 + int(parts[1])


def in_shift_window(now, start, end, grace_minutes=0, weekly_off=(), grace_after=None):
	"""True when `now` (datetime) is inside the shift plus grace before it
	(`grace_minutes`) and after it (`grace_after`, default the same).
	Handles night shifts (end before start); the weekly-off day is the day
	the shift started on."""
	names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
	off = {d.strip()[:3].title() for d in (weekly_off or ()) if d and d.strip()}
	s, e, g = _minutes(start), _minutes(end), int(grace_minutes or 0)
	ga = g if grace_after is None else int(grace_after or 0)
	cur = now.hour * 60 + now.minute
	lo = s - g
	hi = e + ga + (1440 if e <= s else 0)
	for day_back in (0, 1):
		a, b = lo - 1440 * day_back, hi - 1440 * day_back
		if a <= cur <= b and names[(now.weekday() - day_back) % 7] not in off:
			return True
	return False
