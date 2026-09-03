"""Compatibility shim for legacy RPC paths.

Some existing clients still call:
    mm_employee_watcher.mm_employee_watcher.api.<method>

The current implementation exposes API methods from:
    mm_employee_watcher.api

Import and re-export both sets of methods so both paths keep working.
"""

from .. import api as _api


heartbeat = _api.heartbeat
get_my_status = _api.get_my_status
record_desktop_activity = _api.record_desktop_activity
start_work = _api.start_work
complete_work = _api.complete_work
end_work = _api.end_work
extend_work = _api.extend_work
mark_blocked = _api.mark_blocked
mark_break = _api.mark_break
record_document_activity = _api.record_document_activity
get_next_work = _api.get_next_work

__all__ = [
	"heartbeat",
	"get_my_status",
	"record_desktop_activity",
	"start_work",
	"complete_work",
	"end_work",
	"extend_work",
	"mark_blocked",
	"mark_break",
	"record_document_activity",
	"get_next_work",
]
