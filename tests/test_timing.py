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

	def test_claim_api_exists(self):
		api = self.read("api.py")
		for name in ("def claim_next_work", "def release_work", "def reassign_work", "def get_reference_work"):
			self.assertIn(name, api)


if __name__ == "__main__":
	unittest.main()
