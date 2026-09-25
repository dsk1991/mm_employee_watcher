import unittest
from datetime import datetime, timedelta
from pathlib import Path

from mm_employee_watcher import timing

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 24, 9, 0, 0)


def at(minutes):
	return T0 + timedelta(minutes=minutes)


class TimeBreakdownTest(unittest.TestCase):
	def test_no_pauses_all_working(self):
		parts = timing.compute_time_breakdown([("Start", at(0))], at(0), at(30))
		self.assertEqual(parts, {"total": 1800.0, "paused": 0.0, "working": 1800.0})

	def test_pause_and_block_are_excluded(self):
		events = [
			("Start", at(0)),
			("Pause", at(10)),
			("Resume", at(15)),
			("Blocked", at(20)),
			("Unblocked", at(30)),
		]
		parts = timing.compute_time_breakdown(events, at(0), at(40))
		self.assertEqual(parts["paused"], 15 * 60)
		self.assertEqual(parts["working"], 25 * 60)

	def test_open_pause_counts_until_end(self):
		parts = timing.compute_time_breakdown([("Pause", at(10))], at(0), at(25))
		self.assertEqual(parts["paused"], 15 * 60)
		self.assertEqual(parts["working"], 10 * 60)

	def test_events_outside_the_session_are_ignored(self):
		events = [("Pause", at(-30)), ("Resume", at(-20)), ("Pause", at(50))]
		parts = timing.compute_time_breakdown(events, at(0), at(40))
		self.assertEqual(parts["paused"], 0.0)

	def test_waiting_seconds(self):
		self.assertEqual(timing.waiting_seconds(at(0), at(5)), 300.0)
		self.assertEqual(timing.waiting_seconds(None, at(5)), 0.0)
		self.assertEqual(timing.waiting_seconds(at(5), at(0)), 0.0)


class PickNextTest(unittest.TestCase):
	def item(self, name, priority=0, zone=None, minutes=0):
		return {"name": name, "priority": priority, "zone": zone, "creation": at(minutes)}

	def test_empty_pool(self):
		self.assertIsNone(timing.pick_next([]))

	def test_priority_beats_zone(self):
		items = [self.item("low-in-zone", 0, "A"), self.item("high", 5, "B")]
		self.assertEqual(timing.pick_next(items, ["A"])["name"], "high")

	def test_zone_beats_age_at_equal_priority(self):
		items = [self.item("old-b", 0, "B", 0), self.item("new-a", 0, "A", 10)]
		self.assertEqual(timing.pick_next(items, ["a"])["name"], "new-a")

	def test_oldest_first_without_zones(self):
		items = [self.item("new", minutes=10), self.item("old", minutes=1)]
		self.assertEqual(timing.pick_next(items)["name"], "old")


class SuggestionsTest(unittest.TestCase):
	def texts(self, stats):
		return [t["text"] for t in timing.build_suggestions(stats)]

	def test_idle_with_assigned_work_points_to_it(self):
		tips = self.texts({"status": "IDLE", "idle_minutes": 20, "assigned_count": 2, "top_assigned": "Picking"})
		self.assertIn("Picking", tips[0])
		self.assertIn("20", tips[0])

	def test_idle_with_pool_suggests_next_task(self):
		tips = self.texts({"status": "IDLE", "idle_minutes": 5, "pool_count": 3})
		self.assertIn("NEXT TASK", tips[0])

	def test_high_pause_share_warns(self):
		tips = self.texts({"status": "WORKING", "today_working_min": 60, "today_paused_min": 40, "today_sessions": 1})
		self.assertTrue(any("pause" in t for t in tips))

	def test_low_on_time_warns_and_high_praises(self):
		self.assertTrue(any("target" in t for t in self.texts({"on_time_pct": 40, "today_sessions": 1})))
		self.assertTrue(any("Shabash" in t for t in self.texts({"on_time_pct": 95, "period_sessions": 8, "today_sessions": 1})))

	def test_always_returns_something(self):
		self.assertTrue(timing.build_suggestions({}))


class ShiftAndDistanceTest(unittest.TestCase):
	def test_day_shift_with_grace(self):
		mon = datetime(2026, 9, 21, 9, 0)  # Monday
		self.assertTrue(timing.in_shift_window(mon.replace(hour=9, minute=20), "09:30", "18:00", 15))
		self.assertFalse(timing.in_shift_window(mon.replace(hour=8, minute=0), "09:30", "18:00", 15))
		self.assertTrue(timing.in_shift_window(mon.replace(hour=18, minute=10), "09:30", "18:00", 15))
		self.assertFalse(timing.in_shift_window(mon.replace(hour=18, minute=30), "09:30", "18:00", 15))

	def test_weekly_off(self):
		sun = datetime(2026, 9, 27, 12, 0)
		self.assertFalse(timing.in_shift_window(sun, "09:30", "18:00", 0, ["Sun"]))
		self.assertTrue(timing.in_shift_window(sun, "09:30", "18:00", 0, []))

	def test_night_shift_crosses_midnight(self):
		late = datetime(2026, 9, 21, 23, 30)
		early = datetime(2026, 9, 22, 2, 0)
		self.assertTrue(timing.in_shift_window(late, "22:00", "06:00"))
		self.assertTrue(timing.in_shift_window(early, "22:00", "06:00"))
		self.assertFalse(timing.in_shift_window(datetime(2026, 9, 22, 12, 0), "22:00", "06:00"))

	def test_night_shift_weekly_off_uses_start_day(self):
		# Sunday-night shift running into Monday morning is still the Sunday shift
		mon_early = datetime(2026, 9, 28, 2, 0)
		self.assertFalse(timing.in_shift_window(mon_early, "22:00", "06:00", 0, ["Sun"]))

	def test_distance(self):
		self.assertAlmostEqual(timing.haversine_m(26.2389, 73.0243, 26.2389, 73.0243), 0, places=3)
		d = timing.haversine_m(26.2389, 73.0243, 26.2389, 73.0343)
		self.assertTrue(950 < d < 1050)


class WmsWiringTest(unittest.TestCase):
	def read(self, *parts):
		return (ROOT / "mm_employee_watcher" / Path(*parts)).read_text(encoding="utf-8")

	def test_pick_list_events_are_registered(self):
		hooks = self.read("hooks.py")
		for event in ("after_insert", "on_submit", "on_cancel"):
			self.assertIn(event, hooks)
		self.assertIn("mm_employee_watcher.wms_events.handle_document_event", hooks)
		self.assertIn('"Employee Work Queue"]', hooks)

	def test_handler_is_gated_and_non_blocking(self):
		events = self.read("wms_events.py")
		self.assertIn("wms_auto_queue_enabled", events)
		self.assertIn("frappe.log_error", events)
		self.assertIn("source_key", events)

	def test_patch_is_registered(self):
		self.assertIn("v0_4_0_wms_activities", self.read("patches.txt"))
		self.assertTrue((ROOT / "mm_employee_watcher" / "patches" / "v0_4_0_wms_activities.py").exists())

	def test_dashboard_and_nudge_wiring(self):
		self.assertIn("def get_my_dashboard", self.read("api.py"))
		self.assertIn("def nudge_idle_employees", self.read("tasks.py"))
		self.assertIn("nudge_idle_employees", self.read("hooks.py"))

	def test_sections_attendance_wiring(self):
		self.assertTrue((ROOT / "mm_employee_watcher" / "sections.py").exists())
		api = self.read("api.py")
		for name in ("def punch", "def get_punch_status", "def _attendance_summary"):
			self.assertIn(name, api)
		self.assertIn("complete_sections_on_submit", self.read("hooks.py"))
		for doctype in ("employee_punch",):
			folder = ROOT / "mm_employee_watcher" / "mm_employee_watcher" / "doctype" / doctype
			for ext in ("json", "py"):
				self.assertTrue((folder / f"{doctype}.{ext}").exists())

	def test_claim_api_exists(self):
		api = self.read("api.py")
		for name in ("def claim_next_work", "def release_work", "def reassign_work", "def get_reference_work"):
			self.assertIn(name, api)


if __name__ == "__main__":
	unittest.main()
