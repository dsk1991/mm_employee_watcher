# WMS integration contract

`mm_employee_watcher` stays the single source of truth. The Android WMS app
must not keep a second employee-status database or send an Employee ID chosen
from the UI. Frappe resolves the employee from the authenticated API user's
`Employee.user_id` link.

## Recommended Android lifecycle

1. On foreground/login, call `get_my_status`. It records an immediate
   heartbeat and returns `tracking: false` for users excluded in the User
   master.
2. While the app is visible, call `heartbeat` every four minutes. Stop the
   timer in the background. The server changes a stale client to `OFFLINE`;
   Android must not fake `IDLE` locally.
3. Render one compact work bar from `get_my_status` at the top of every WMS
   page. The bar shows status, activity, completed/target quantity, and time
   remaining. Do not create a separate WMS tracking setting; the existing
   `User.mm_tracking_enabled` value applies everywhere.

## Section lifecycle

Every tracked activity belongs to the employee's one active section. Before
starting a Pick List or Putaway, WMS must start (or reuse) the physical section:

```text
POST /api/method/mm_employee_watcher.api.start_section
work_section=Sales Warehouse
target_minutes=120
source_app=WMS
qr_code=SALES-WH-01
```

If the section is configured with `Requires QR Scan`, the matching QR value is
mandatory. Repeating the same start is idempotent; starting a different section
while one is active returns a conflict. After the employee taps End Section:

```text
POST /api/method/mm_employee_watcher.api.end_section
section_session=ESS-00001
reason=Scheduled warehouse block completed
completed_qty=120
```

The server closes any current activity in that section, clears the current
section, and returns the next scheduled section. The client must then show
"Please start new work". A plain heartbeat must never change sections; only an
explicit section start/end can do that, so an old Desk browser tab cannot steal
the employee back from WMS.

## Document-backed operations

When the employee explicitly starts a Pick List, Putaway, or Delivery Count,
call this after `start_section`:

```text
POST /api/method/mm_employee_watcher.api.start_reference_work
work_activity=Picking
reference_doctype=Pick List
reference_name=MAT-PICK-2026-00001
target_qty=120
target_minutes=60
source_app=WMS
```

The call is idempotent for the authenticated employee and reference. Repeated
taps return the same session. If that employee is already doing different
primary work, the server returns a conflict that WMS should display instead of
silently replacing the active work.

After a successful partial save, send the aggregate completed quantity:

```text
POST /api/method/mm_employee_watcher.api.update_progress
work_session=EWS-00001
completed_qty=42
```

After the operational document reaches its real completion point, call:

```text
POST /api/method/mm_employee_watcher.api.complete_reference_work
reference_doctype=Pick List
reference_name=MAT-PICK-2026-00001
completed_qty=120
```

For Picking, completion means successful Pick List submit. For Delivery Count,
it means the saved/confirmed counting step chosen by the business—not merely
opening the document. For Putaway, complete only after every required target
rack/batch row is saved and the operational document is finalized. A future
server-side DocType hook should be the final safety net; the mobile completion
call gives immediate UI feedback but must not redefine ERPNext/WMS completion.

## Current WMS code placement

The native WMS app currently builds every screen inside one
`MainActivity.java`. Add the compact watcher bar in the common `page(...)`
builder so it appears consistently. Add a main-thread `Handler` heartbeat in
`onStart`/`onStop`, and make API calls through the existing authenticated
`Api.request(...)` helper. Keep watcher calls best-effort: a tracking-network
error must be logged and shown in the bar, but must not discard a valid Pick
List/Putaway save.

## Security rules

- Use a dedicated API user linked to exactly one active Employee.
- Never send `employee` from the WMS client for ordinary work calls.
- Never store a second “tracking enabled” flag on the device.
- Do not retry non-idempotent POST calls blindly. `start_reference_work` and
  `complete_reference_work` are specifically safe to retry; progress updates
  are absolute quantities and therefore safe to repeat.
