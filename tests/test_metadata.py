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
		self.assertNotIn("mm-work-bar", script)

	def test_migration_patch_registered(self):
		patches = (ROOT / "mm_employee_watcher" / "patches.txt").read_text(encoding="utf-8")
		self.assertIn("mm_employee_watcher.patches.v0_3_0_remove_sections", patches)
		self.assertTrue(
			(ROOT / "mm_employee_watcher" / "patches" / "v0_3_0_remove_sections.py").exists()
		)

	def test_dashboard_public_rpc_path_exists(self):
		dashboard = (ROOT / "mm_employee_watcher" / "dashboard.py").read_text(encoding="utf-8")
		self.assertIn("from .mm_employee_watcher.dashboard import get_dashboard_data", dashboard)
		page = (ROOT / "mm_employee_watcher" / "www" / "mm_dashboard.html").read_text(
			encoding="utf-8"
		)
		self.assertIn("mm_employee_watcher.dashboard.get_dashboard_data", page)


if __name__ == "__main__":
	unittest.main()
