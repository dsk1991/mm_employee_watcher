import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "mm_employee_watcher" / "mm_employee_watcher" / "mm_employee_watcher" / "doctype"


def load_doctype(folder, filename):
	return json.loads((DOCTYPE_ROOT / folder / filename).read_text(encoding="utf-8"))


class MetadataTest(unittest.TestCase):
	def test_all_doctype_json_is_valid(self):
		files = list(DOCTYPE_ROOT.rglob("*.json"))
		self.assertTrue(files)
		for path in files:
			with self.subTest(path=path):
				json.loads(path.read_text(encoding="utf-8"))

	def test_session_has_pause_expiry_and_queue_fields(self):
		data = load_doctype("employee_work_session", "employee_work_session.json")
		fields = {field["fieldname"]: field for field in data["fields"]}
		self.assertIn("Paused", fields["status"]["options"].splitlines())
		self.assertIn("expiry_notified_at", fields)
		self.assertIn("queue_item", fields)
		self.assertIn("work_section", fields)
		self.assertIn("section_session", fields)

	def test_section_and_schedule_doctypes_have_required_contract(self):
		section = load_doctype("work_section_master", "work_section_master.json")
		section_fields = {field["fieldname"] for field in section["fields"]}
		self.assertTrue({"section_name", "section_type", "default_duration_minutes"} <= section_fields)

		session = load_doctype("employee_section_session", "employee_section_session.json")
		session_fields = {field["fieldname"] for field in session["fields"]}
		self.assertTrue(
			{"employee", "work_section", "status", "start_time", "target_end_time"} <= session_fields
		)

		schedule = load_doctype("employee_section_schedule", "employee_section_schedule.json")
		schedule_fields = {field["fieldname"] for field in schedule["fields"]}
		self.assertTrue(
			{"employee", "work_section", "scheduled_start", "scheduled_end"} <= schedule_fields
		)

	def test_current_status_carries_one_active_section(self):
		data = load_doctype("employee_current_status", "employee_current_status.json")
		fields = {field["fieldname"] for field in data["fields"]}
		self.assertIn("current_section", fields)
		self.assertIn("current_section_session", fields)

	def test_employee_role_cannot_write_tracking_records_directly(self):
		for folder, filename in (
			("employee_section_session", "employee_section_session.json"),
			("employee_section_schedule", "employee_section_schedule.json"),
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

	def test_section_mutations_use_actor_guard(self):
		tree = ast.parse((ROOT / "mm_employee_watcher" / "api.py").read_text(encoding="utf-8"))
		functions = {
			node.name: node
			for node in tree.body
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
		}
		for function_name in ("extend_section", "end_section"):
			with self.subTest(function=function_name):
				calls = {
					node.func.id
					for node in ast.walk(functions[function_name])
					if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
				}
				self.assertIn("_get_section_for_actor", calls)

	def test_invoice_and_payment_hooks_record_activity(self):
		hooks = (ROOT / "mm_employee_watcher" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn('"Sales Invoice"', hooks)
		self.assertIn('"Payment Entry"', hooks)
		self.assertIn("record_document_activity", hooks)


if __name__ == "__main__":
	unittest.main()
