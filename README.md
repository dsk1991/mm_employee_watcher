# mm_employee_watcher

Smart Employee Work Watcher for **Frappe Framework / ERPNext v16** — a
shared backend that tracks what every employee is doing right now
(WORKING / IDLE / BREAK / BLOCKED / OFFLINE), across ERPNext Desk, WMS,
Android HHT, and any other client, through one set of DocTypes and
whitelisted APIs.

Requires **ERPNext v16**. HRMS is optional in this release; it will become a
required dependency only when attendance gating/reporting is implemented.

See [`docs/backend-architecture.md`](docs/backend-architecture.md) (English)
and [`docs/backend-architecture-hi.md`](docs/backend-architecture-hi.md)
(Hindi) for the full design.

## What's in this cut

- DocTypes: `Work Activity Master`, `Employee Work Session`,
  `Employee Current Status`, `Employee Work Log`, `Employee Work Queue`
- Server-side rule: one Primary Active Work per employee at a time
- Whitelisted API: `start_work`, `complete_work`, `extend_work`,
  `pause_work`, `resume_work`, `mark_blocked`, `get_my_status`,
  `get_next_work`, `heartbeat`, plus WMS-safe `start_reference_work`,
  `update_progress`, and `complete_reference_work`
- Employee-facing mutations are ownership checked. An employee cannot pass
  another Employee or Work Session name and write through
  `ignore_permissions`; only System Manager or Employee Watcher Manager can
  act on behalf of someone else.
- Work sessions use explicit `Active → Paused/Blocked/Completed` transitions,
  queue items close as `Completed`, and expiry alerts are emitted once per
  target time (an extension arms the alert again).
- Scheduled jobs: expired-session sweep (server-side "target time is up"
  → `publish_realtime`) and an offline/no-heartbeat watchdog
- **Employee = logged-in User.** `Employee.user_id` resolves who's asking
  on every API call — no employee picker needed, login is enough.
- **Per-user tracking on/off switch** — a Custom Field
  (`mm_tracking_enabled`) added to the standard User form on install.
  Unchecked users are invisible to the watcher: no popups, no scheduler
  actions, no state changes.
- **Desk popup** (`public/js/mm_watcher.js`, loaded on every Desk page):
  - No active work? → **"Work Now"** dialog (Work, Description, Start
    Time, Duration, Target Qty) as soon as Desk opens.
  - Active session's target time expired? → **Done / Extend / Blocked**
    dialog, pushed in real time via `frappe.publish_realtime`.
- **Auto-chain on Done.** `complete_work` immediately looks at
  `Employee Work Queue` and auto-starts the next pending item for that
  employee — no idle gap, no manual Start tap. Only when the queue is
  empty does the employee go `IDLE` and get the "Work Now" popup.
- **Wall-display dashboard** at `/mm_dashboard` — a standalone page (not
  inside Desk), openable by URL from any browser/TV, auto-refreshing
  every 30 seconds. Live cards per employee (status, current work,
  qty done/target, time left or overdue, blocked reason) plus a status
  count strip at the top. See "Wall-display dashboard" below.
- **WMS integration contract** in
  [`docs/wms-integration.md`](docs/wms-integration.md): foreground heartbeat,
  one compact work bar, idempotent document start, progress sync, and final
  completion calls.

**Not yet built** (later phases from the design doc): the always-visible
in-Desk Smart Work Bar strip, the daily productivity report, FCM push
delivery for a closed mobile app, and the WMS/Production
auto-completion hooks (Packing Job, Pick List, Putaway, Job Card).

## Install (on a bench)

```bash
bench get-app --branch main https://github.com/dsk1991/mm_employee_watcher.git
bench --site your-site install-app mm_employee_watcher
bench build --app mm_employee_watcher   # picks up public/js/mm_watcher.js
```

For an existing installation, update and migrate normally. The idempotent
`after_migrate` hook creates any missing tracking field and app roles:

```bash
bench --site your-site migrate
bench build --app mm_employee_watcher
bench restart
```

If a previous failed deployment did not run hooks, this recovery command is
also safe to run more than once:

```bash
bench --site your-site execute mm_employee_watcher.install.run_if_not_already_installed
```

## Wall-display dashboard

Open `https://your-site/mm_dashboard` in any browser and put it on a TV or
monitor — it refreshes itself every 30 seconds with no interaction needed.

It requires a logged-in session (the browser's cookie), same as any other
Desk page — an unauthenticated visitor is bounced to `/login`. For a TV
that should just stay on the dashboard forever, the simplest setup is:

1. Create a dedicated user, e.g. `dashboard@yourcompany.com`, with a role
   **Employee Watcher Viewer** role. Use **Employee Watcher Manager** for
   supervisors who also maintain activities and work queues. Ordinary
   Employee users cannot open the all-employee dashboard.
2. Log in as that user once on the TV's browser and leave it signed in —
   the session cookie persists, so the TV keeps showing the dashboard
   indefinitely without anyone re-entering credentials.
3. Point the browser at `/mm_dashboard` and leave it there (most smart TVs
   / Chromecast-with-a-kiosk-browser / a cheap mini-PC in browser
   full-screen mode all work).

The data itself comes from one whitelisted call,
`mm_employee_watcher.dashboard.get_dashboard_data`,
which the page's JS re-fetches every 30s — so the dashboard can just as
easily be embedded in an iframe elsewhere, or polled by another tool.

## Repo layout

```
mm_employee_watcher/
  mm_employee_watcher/            # the installable Frappe app (Python package)
    hooks.py                      # scheduler_events, app_include_js, after_install
    install.py                    # creates the User "Enable Work Tracking" field
    api.py                        # whitelisted methods (start_work, etc.)
    dashboard.py                  # get_dashboard_data — feeds /mm_dashboard
    tasks.py                      # scheduled jobs
    utils.py                      # shared helpers (status transitions, realtime)
    public/js/mm_watcher.js       # Desk popups: Work Now / Done-Extend-Blocked
    www/mm_dashboard.html         # the wall-display dashboard page
    www/mm_dashboard.py           # page context (redirects Guests to /login)
    mm_employee_watcher/doctype/  # the 5 DocTypes
docs/
  backend-architecture.md         # design doc (English)
  backend-architecture-hi.md      # design doc (Hindi)
```
