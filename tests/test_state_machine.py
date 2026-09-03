import unittest

from mm_employee_watcher.state_machine import (
	SESSION_ACTIVE,
	SESSION_BLOCKED,
	SESSION_CANCELLED,
	SESSION_COMPLETED,
	SESSION_EXTENDED,
	SESSION_PAUSED,
	SECTION_ACTIVE,
	SECTION_CANCELLED,
	SECTION_COMPLETED,
	ensure_section_transition,
	ensure_transition,
)


class WorkSessionStateMachineTest(unittest.TestCase):
	def test_expected_open_transitions_are_allowed(self):
		for current, next_status in (
			(SESSION_ACTIVE, SESSION_EXTENDED),
			(SESSION_ACTIVE, SESSION_PAUSED),
			(SESSION_EXTENDED, SESSION_BLOCKED),
			(SESSION_PAUSED, SESSION_ACTIVE),
			(SESSION_BLOCKED, SESSION_ACTIVE),
			(SESSION_BLOCKED, SESSION_COMPLETED),
		):
			with self.subTest(current=current, next_status=next_status):
				ensure_transition(current, next_status)

	def test_terminal_sessions_cannot_be_reopened(self):
		for current in (SESSION_COMPLETED, SESSION_CANCELLED):
			with self.subTest(current=current):
				with self.assertRaises(ValueError):
					ensure_transition(current, SESSION_ACTIVE)

	def test_unknown_transition_is_rejected(self):
		with self.assertRaises(ValueError):
			ensure_transition("Unknown", SESSION_ACTIVE)

	def test_section_can_close_but_cannot_reopen(self):
		for terminal in (SECTION_COMPLETED, SECTION_CANCELLED):
			with self.subTest(terminal=terminal):
				ensure_section_transition(SECTION_ACTIVE, terminal)
				with self.assertRaises(ValueError):
					ensure_section_transition(terminal, SECTION_ACTIVE)


if __name__ == "__main__":
	unittest.main()
