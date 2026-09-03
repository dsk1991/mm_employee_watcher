"""Pure work-session state rules shared by APIs, DocTypes, and tests."""

SESSION_ACTIVE = "Active"
SESSION_EXTENDED = "Extended"
SESSION_PAUSED = "Paused"
SESSION_BLOCKED = "Blocked"
SESSION_COMPLETED = "Completed"
SESSION_CANCELLED = "Cancelled"

OPEN_SESSION_STATUSES = frozenset(
	{
		SESSION_ACTIVE,
		SESSION_EXTENDED,
		SESSION_PAUSED,
		SESSION_BLOCKED,
	}
)

ALLOWED_TRANSITIONS = {
	SESSION_ACTIVE: frozenset(
		{SESSION_EXTENDED, SESSION_PAUSED, SESSION_BLOCKED, SESSION_COMPLETED, SESSION_CANCELLED}
	),
	SESSION_EXTENDED: frozenset(
		{SESSION_EXTENDED, SESSION_PAUSED, SESSION_BLOCKED, SESSION_COMPLETED, SESSION_CANCELLED}
	),
	SESSION_PAUSED: frozenset(
		{SESSION_ACTIVE, SESSION_BLOCKED, SESSION_COMPLETED, SESSION_CANCELLED}
	),
	SESSION_BLOCKED: frozenset(
		{SESSION_ACTIVE, SESSION_PAUSED, SESSION_COMPLETED, SESSION_CANCELLED}
	),
	SESSION_COMPLETED: frozenset(),
	SESSION_CANCELLED: frozenset(),
}


def ensure_transition(current_status: str, next_status: str) -> None:
	"""Raise ValueError when a persisted session attempts an invalid transition."""
	if current_status == next_status:
		return
	if next_status not in ALLOWED_TRANSITIONS.get(current_status, frozenset()):
		raise ValueError(f"Work session cannot change from {current_status} to {next_status}")
