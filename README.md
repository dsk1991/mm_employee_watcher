# mm_employee_watcher

Smart Employee Work Watcher for Frappe / ERPNext — a shared backend that tracks
what every employee is doing right now (WORKING / IDLE / BREAK / BLOCKED /
OFFLINE), across ERPNext Desk, WMS, Android HHT, and any other client, through
one set of DocTypes and whitelisted APIs.

See [`docs/backend-architecture.md`](docs/backend-architecture.md) (English)
and [`docs/backend-architecture-hi.md`](docs/backend-architecture-hi.md)
(Hindi) for the full design.

## What's in this first cut

This is the **foundation** layer only (build-order phases 1-3 from the design
doc):

- DocTypes: `Work Activity Master`, `Employee Work Session`,
  `Employee Current Status`, `Employee Work Log`, `Employee Work Queue`
- Server-side rule: one Primary Active Work per employee at a time
- Whitelisted API: `start_work`, `complete_work`, `extend_work`,
  `pause_work`, `resume_work`, `mark_blocked`, `get_my_status`,
  `get_next_work`, `heartbeat`
- Scheduled jobs: expired-session sweep (fires `publish_realtime` +
  auto-marks `Employee Current Status` = `IDLE`) and an offline/no-heartbeat
  watchdog

**Not yet built** (later phases from the design doc): the Smart Work Bar
front-end widget, the Supervisor dashboard + daily report, FCM push
delivery, and the WMS/Production auto-completion hooks (Packing Job, Pick
List, Putaway, Job Card).

## Install (on a bench)

```bash
bench get-app mm_employee_watcher /path/to/this/repo
bench --site your-site install-app mm_employee_watcher
```

## Repo layout

```
mm_employee_watcher/
  mm_employee_watcher/            # the installable Frappe app (Python package)
    hooks.py                      # scheduler_events, app config
    api.py                        # whitelisted methods (start_work, etc.)
    tasks.py                      # scheduled jobs
    utils.py                      # shared helpers (status transitions, realtime)
    mm_employee_watcher/doctype/  # the 5 DocTypes
docs/
  backend-architecture.md         # design doc (English)
  backend-architecture-hi.md      # design doc (Hindi)
```
