import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "mm_employee_watcher" / "mm_employee_watcher" / "doctype"

SECTION_FIELDNAMES = {
	"work_section",
	"section_session",
	"current_section",
	"current_section_session",
}


def load_doctype(folder, filename):
	return json.loads((DOCTYPE_ROOT / folder / filename).read_text(encoding="utf-8"))


class MetadataTest(unittest.TestCase):
	def test_all_doctype_json_is_valid(self):
		files = list(DOCTYPE_ROOT.rglob("*.json"))
		self.assertTrue(files)
		for path in files:
			with self.subTest(path=path):
				data = json.loads(path.read_text(encoding="utf-8"))
				self.assertEqual(data["module"], "MM Employee Watcher")

	def test_session_has_pause_expiry_and_queue_fields_but_no_section(self):
		data = load_doctype("employee_work_session", "employee_work_session.json")
		fields = {field["fieldname"]: field for field in data["fields"]}
		self.assertIn("Paused", fields["status"]["options"].splitlines())
		self.assertIn("expiry_notified_at", fields)
		self.assertIn("queue_item", fields)
		self.assertNotIn("work_section", fields)
		self.assertNotIn("section_session", fields)

	def test_current_status_has_no_section_fields(self):
		data = load_doctype("employee_current_status", "employee_current_status.json")
		fields = {field["fieldname"] for field in data["fields"]}
		self.assertIn("current_session", fields)
		self.assertFalse(SECTION_FIELDNAMES & fields)

	def test_section_doctypes_are_gone(self):
		for folder in ("work_section_master", "employee_section_session", "employee_section_schedule"):
			with self.subTest(folder=folder):
				self.assertFalse((DOCTYPE_ROOT / folder).exists())

	def test_no_section_fields_remain_in_any_doctype(self):
		for path in DOCTYPE_ROOT.rglob("*.json"):
			data = json.loads(path.read_text(encoding="utf-8"))
			fieldnames = {field["fieldname"] for field in data.get("fields", [])}
			with self.subTest(path=path.name):
				self.assertFalse(SECTION_FIELDNAMES & fieldnames)
			options = " ".join(
				field.get("options", "") for field in data.get("fields", []) if field.get("fieldtype") == "Link"
			)
			self.assertNotIn("Work Section Master", options)
			self.assertNotIn("Employee Section Session", options)

	def test_employee_role_cannot_write_tracking_records_directly(self):
		for folder, filename in (
			("employee_current_status", "employee_current_status.json"),
			("employee_work_log", "employee_work_log.json"),
			("employee_work_session", "employee_work_session.json"),
			("employee_work_queue", "employee_work_queue.json"),
		):
			with self.subTest(doctype=folder):
				permissions = load_doctype(folder, filename)["permissions"]
				employee_permissions = [row for row in permissions if row.get("role") == "Employee"]
				self.assertFalse(employee_permissions)

	def test_queue_supports_completed_state(self):
		data = load_doctype("employee_work_queue", "employee_work_queue.json")
		status = next(field for field in data["fields"] if field["fieldname"] == "status")
		self.assertIn("Completed", status["options"].splitlines())

	def test_session_mutations_use_actor_guard(self):
		tree = ast.parse((ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8"))
		functions = {
			node.name: node
			for node in tree.body
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
		}
		for function_name in (
			"complete_work",
			"end_work",
			"update_progress",
			"extend_work",
			"pause_work",
			"resume_work",
			"mark_blocked",
		):
			with self.subTest(function=function_name):
				calls = {
					node.func.id
					for node in ast.walk(functions[function_name])
					if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
				}
				self.assertIn("_get_session_for_actor", calls)

	def test_employee_override_is_guarded(self):
		tree = ast.parse((ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8"))
		start_work = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start_work")
		calls = {
			node.func.id
			for node in ast.walk(start_work)
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
		}
		self.assertIn("_get_employee_for_user", calls)

	def test_no_section_api_remains(self):
		api = (ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8")
		for token in ("def start_section", "def end_section", "def extend_section", "get_active_section_session"):
			self.assertNotIn(token, api)

	def test_invoice_and_payment_hooks_record_activity(self):
		hooks = (ROOT / "mm_employee_watcher" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn('"Sales Invoice"', hooks)
		self.assertIn('"Payment Entry"', hooks)
		self.assertIn("record_document_activity", hooks)

	def test_scheduler_has_no_section_jobs(self):
		hooks = (ROOT / "mm_employee_watcher" / "hooks.py").read_text(encoding="utf-8")
		self.assertNotIn("check_expired_sections", hooks)
		self.assertNotIn("notify_due_section_schedules", hooks)

	def test_work_dialog_reads_live_description_value(self):
		script = (ROOT / "mm_employee_watcher" / "public" / "js" / "mm_employee_watcher.bundle.js").read_text(
			encoding="utf-8"
		)
		self.assertIn('d.get_field("description")', script)
		self.assertIn("descriptionControl.$input.val()", script)
		self.assertIn("description: description", script)

	def test_desk_js_has_floating_widget(self):
		script = (ROOT / "mm_employee_watcher" / "public" / "js" / "mm_employee_watcher.bundle.js").read_text(
			encoding="utf-8"
		)
		self.assertIn("mm-fab", script)
		self.assertIn("mm_employee_watcher.api.end_work", script)
		self.assertIn("lock_dialog", script)
		self.assertIn("set_minimized", script)
		self.assertIn("2 * 60 * 1000", script)  # idle re-prompt interval
		self.assertIn("record_screen_view", script)
		self.assertNotIn("mm-work-bar", script)

	def test_dashboard_has_employee_drilldown(self):
		impl = (
			ROOT / "mm_employee_watcher" / "mm_employee_watcher" / "dashboard.py"
		).read_text(encoding="utf-8")
		self.assertIn("def get_employee_detail", impl)
		shim = (ROOT / "mm_employee_watcher" / "dashboard.py").read_text(encoding="utf-8")
		self.assertIn("get_employee_detail", shim)
		page = (ROOT / "mm_employee_watcher" / "www" / "mm_dashboard.html").read_text(encoding="utf-8")
		self.assertIn("get_employee_detail", page)
		self.assertIn("openDetail", page)
		api = (ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8")
		self.assertIn("def record_screen_view", api)

	def test_supervisor_alerts_wired(self):
		hooks = (ROOT / "mm_employee_watcher" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn("raise_supervisor_alerts", hooks)
		tasks = (ROOT / "mm_employee_watcher" / "tasks.py").read_text(encoding="utf-8")
		self.assertIn("def raise_supervisor_alerts", tasks)
		self.assertIn("Notification Log", tasks)
		for folder in ("employee_watcher_alert", "mm_watcher_settings", "mm_watcher_alert_recipient"):
			self.assertTrue((DOCTYPE_ROOT / folder).exists(), folder)
		alert = load_doctype("employee_watcher_alert", "employee_watcher_alert.json")
		fields = {f["fieldname"] for f in alert["fields"]}
		self.assertTrue({"alert_type", "status", "raised_at", "cleared_at", "open_minutes"} <= fields)
		self.assertIn("Idle", next(f for f in alert["fields"] if f["fieldname"] == "alert_type")["options"].splitlines())
		settings = load_doctype("mm_watcher_settings", "mm_watcher_settings.json")
		self.assertEqual(settings.get("issingle"), 1)
		s_fields = {f["fieldname"] for f in settings["fields"]}
		self.assertTrue({"alerts_enabled", "idle_alert_minutes", "alert_recipients"} <= s_fields)
		utils = (ROOT / "mm_employee_watcher" / "utils.py").read_text(encoding="utf-8")
		self.assertIn("def get_watcher_settings", utils)
		script = (ROOT / "mm_employee_watcher" / "public" / "js" / "mm_employee_watcher.bundle.js").read_text(
			encoding="utf-8"
		)
		self.assertIn("mm_employee_watcher:supervisor_alert", script)

	def test_queue_schedule_and_break_overrun_wired(self):
		hooks = (ROOT / "mm_employee_watcher" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn("build_scheduled_queues", hooks)
		self.assertIn("check_break_overrun", hooks)
		tasks = (ROOT / "mm_employee_watcher" / "tasks.py").read_text(encoding="utf-8")
		self.assertIn("def build_scheduled_queues", tasks)
		self.assertIn("def check_break_overrun", tasks)
		for folder in ("work_queue_schedule", "work_queue_schedule_assignee"):
			self.assertTrue((DOCTYPE_ROOT / folder).exists(), folder)
		sch = load_doctype("work_queue_schedule", "work_queue_schedule.json")
		s_fields = {f["fieldname"] for f in sch["fields"]}
		self.assertTrue(
			{"recurrence", "weekday", "day_of_month", "specific_dates", "assignees", "last_run_date"}
			<= s_fields
		)
		rec = next(f for f in sch["fields"] if f["fieldname"] == "recurrence")
		self.assertEqual(
			set(rec["options"].splitlines()), {"Daily", "Weekly", "Monthly", "Specific Dates"}
		)
		queue = load_doctype("employee_work_queue", "employee_work_queue.json")
		q_fields = {f["fieldname"] for f in queue["fields"]}
		self.assertTrue({"schedule", "for_date", "instructions"} <= q_fields)
		status = load_doctype("employee_current_status", "employee_current_status.json")
		self.assertIn("break_until", {f["fieldname"] for f in status["fields"]})
		api = (ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8")
		self.assertIn("def get_my_queue", api)
		self.assertIn("def start_queue_item", api)
		wlog = load_doctype("employee_work_log", "employee_work_log.json")
		opts = next(f for f in wlog["fields"] if f["fieldname"] == "event_type")["options"].splitlines()
		self.assertIn("Break Start", opts)
		self.assertIn("Break End", opts)

	def test_report_and_retention(self):
		report_dir = (
			ROOT / "mm_employee_watcher" / "mm_employee_watcher" / "report" / "employee_work_report"
		)
		self.assertTrue((report_dir / "employee_work_report.py").exists())
		rjson = json.loads((report_dir / "employee_work_report.json").read_text(encoding="utf-8"))
		self.assertEqual(rjson["report_type"], "Script Report")
		self.assertEqual(rjson["module"], "MM Employee Watcher")
		rpy = (report_dir / "employee_work_report.py").read_text(encoding="utf-8")
		self.assertIn("def execute", rpy)
		hooks = (ROOT / "mm_employee_watcher" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn("purge_old_records", hooks)
		tasks = (ROOT / "mm_employee_watcher" / "tasks.py").read_text(encoding="utf-8")
		self.assertIn("def purge_old_records", tasks)
		settings = load_doctype("mm_watcher_settings", "mm_watcher_settings.json")
		s_fields = {f["fieldname"] for f in settings["fields"]}
		self.assertTrue({"log_retention_days", "alert_retention_days"} <= s_fields)
		script = (ROOT / "mm_employee_watcher" / "public" / "js" / "mm_employee_watcher.bundle.js").read_text(
			encoding="utf-8"
		)
		self.assertIn("data-mm-resume", script)
		self.assertIn("mm_employee_watcher.api.resume_work", script)

	def test_queue_does_not_auto_start(self):
		api = (ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8")
		self.assertNotIn("_start_next_from_queue", api)
		self.assertNotIn("auto_started", api)
		impl = (
			ROOT / "mm_employee_watcher" / "mm_employee_watcher" / "dashboard.py"
		).read_text(encoding="utf-8")
		self.assertIn("def add_queue_item", impl)
		self.assertIn("def get_queue_form_data", impl)
		shim = (ROOT / "mm_employee_watcher" / "dashboard.py").read_text(encoding="utf-8")
		self.assertIn("add_queue_item", shim)
		page = (ROOT / "mm_employee_watcher" / "www" / "mm_dashboard.html").read_text(encoding="utf-8")
		self.assertIn("add_queue_item", page)
		self.assertIn("/app/work-queue-schedule", page)
		script = (ROOT / "mm_employee_watcher" / "public" / "js" / "mm_employee_watcher.bundle.js").read_text(
			encoding="utf-8"
		)
		self.assertNotIn("auto_started", script)

	def test_tracking_is_opt_in(self):
		utils = (ROOT / "mm_employee_watcher" / "utils.py").read_text(encoding="utf-8")
		fn = utils.split("def is_tracking_enabled")[1].split("\ndef ")[0]
		# no branch returns True for a missing user / unset value any more
		self.assertNotIn("return True", fn)
		self.assertIn("return False", fn)
		install = (ROOT / "mm_employee_watcher" / "install.py").read_text(encoding="utf-8")
		self.assertIn('"default": "0"', install)
		self.assertNotIn('"default": "1"', install.split("mm_tracking_enabled")[1][:400])

	def test_migration_patch_registered(self):
		patches = (ROOT / "mm_employee_watcher" / "patches.txt").read_text(encoding="utf-8")
		self.assertIn("mm_employee_watcher.patches.v0_3_0_remove_sections", patches)
		self.assertTrue(
			(ROOT / "mm_employee_watcher" / "patches" / "v0_3_0_remove_sections.py").exists()
		)

	def test_dashboard_public_rpc_path_exists(self):
		dashboard = (ROOT / "mm_employee_watcher" / "dashboard.py").read_text(encoding="utf-8")
		self.assertIn("from .mm_employee_watcher.dashboard import", dashboard)
		for method in ("get_dashboard_data", "get_dashboard_history", "get_employee_detail"):
			self.assertIn(method, dashboard)
		page = (ROOT / "mm_employee_watcher" / "www" / "mm_dashboard.html").read_text(
			encoding="utf-8"
		)
		self.assertIn("mm_employee_watcher.dashboard.get_dashboard_data", page)
		self.assertIn("mm_employee_watcher.dashboard.get_dashboard_history", page)


if __name__ == "__main__":
	unittest.main()
