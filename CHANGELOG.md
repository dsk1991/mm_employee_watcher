# Changelog

## 0.8.2 - 2026-09-04

- **Fix: Desk navigation no longer auto-completes/switches work sessions.**
  Opening a Sales Invoice, Payment Entry, or report screen used to complete
  the employee's active session ("Automatically changed Desk activity") and
  start a new one for every screen visited, flooding the drill-down with a
  stream of near-zero-minute "Completed" sessions. `record_desktop_activity`
  is now purely a passive Employee Work Log entry — it attaches
  Document Created/Submitted counts to the current session only when its
  activity already matches, and never creates, switches, or completes
  anything. Only the employee's own explicit Start Work / End Work does
  that now.

## 0.8.1 - 2026-09-04

- Performance hardening (no behaviour change):
  - `Employee Work Log.event_time` gets a `search_index` — the dashboard's
    30-second grouped query, the report, and the purge job all filter on it.
  - The idle/break/blocked pairing is now a single O(n) pass
    (`utils.pair_state_durations`), shared by the drill-down, the back-dated
    dashboard, and `Employee Work Report` (which was O(n²)). The report also
    caps its date range at 92 days.
  - `purge_old_records` deletes in 5 000-row batches with a commit between,
    so the first run on a long-neglected table never takes one giant lock.

## 0.8.0 - 2026-09-04

- **Tracking is now opt-in.** `is_tracking_enabled` returns True only when
  the User's "Enable Work Tracking" checkbox is *explicitly ticked* — no
  linked user, no Custom Field, or an unset value all mean "not tracked".
  The Custom Field default changes to unticked, and `after_migrate` fixes an
  existing opt-out field to opt-in. **After upgrading, tick the box on each
  user you want tracked** — everyone else loses the widget, popups, queue
  and dashboard presence.

## 0.7.0 - 2026-09-04

- **Queued work no longer auto-starts.** `_complete_session` just closes the
  session and drops the employee to `IDLE`; `_start_next_from_queue` and the
  auto-chain response fields are gone. The employee starts the next task
  from their queue (widget list or the "Pick from your queue" selector).
  Scheduled tasks stay `Pending` until started.
- **Dashboard queue management.** A toolbar above the grid (managers only)
  with an inline **Add to queue** form (`add_queue_item` /
  `get_queue_form_data`) and links to the `Work Queue Schedule`,
  `Employee Work Queue`, and `Work Activity Master` Desk list views.

## 0.6.1 - 2026-09-04

- **Back-dated dashboard.** `/mm_dashboard` has a date picker; pick a past
  day and the grid switches to that day's per-employee totals (worked /
  idle / break / blocked hours, sessions, qty) via the new
  `get_dashboard_history`. Cards still open the drill-down — now for the
  chosen day. A "← Live" button returns to the live view.

## 0.6.0 - 2026-09-04

- **Employee Work Report** (Script Report) — worked / idle / break / blocked
  hours per employee over a date range, session count, and an average
  efficiency (Work Activity standard duration vs actual). Filters: date
  range, department, employee.
- **Blocked work is recoverable from the widget.** A blocked session now
  gets its own panel — reason + **Unblock & Resume** (calls `resume_work`)
  + End Work — instead of the normal timer view.
- **Data retention.** `MM Watcher Settings` gains `log_retention_days`
  (default 90) and `alert_retention_days` (default 180); a nightly
  `purge_old_records` job trims `Employee Work Log`, cleared
  `Employee Watcher Alert`, and finished `Employee Work Queue` rows. 0 =
  keep forever.

## 0.5.0 - 2026-09-04

- **Employees pick their own work.** `get_my_queue` returns everything
  pending in an employee's `Employee Work Queue`; the widget's idle panel
  lists it with per-task **Start** buttons, and the forced "Work Now" popup
  has a "Pick from your queue" selector. `start_queue_item` starts one
  chosen task and marks the queue row.
- **`Work Queue Schedule` DocType.** A recurring template (Daily / Weekly by
  weekday / Monthly by day-of-month / Specific Dates) that a new hourly job
  (`build_scheduled_queues`, once per schedule per day) turns into queue
  items for its assignees (a table, or a whole department). Carries
  instructions, target qty, priority, and an optional reference. New
  `Employee Work Queue` fields: `schedule`, `for_date`, `instructions`.
- **Break overrun → IDLE.** `mark_break` now takes a planned `minutes` and
  stores `Employee Current Status.break_until`. `check_break_overrun` (per
  minute) flips an employee who is past that time back to IDLE — dated from
  when the break should have ended — so the idle nag and supervisor alert
  fire straight away. The widget shows a dedicated break panel with a
  countdown and a **Resume Work** button.
- Dashboard cards show a "N pending" count.

## 0.4.0 - 2026-09-04

- **Supervisor alerts.** A per-minute job (`raise_supervisor_alerts`) opens
  an `Employee Watcher Alert` when an employee crosses an **Idle**,
  **Overdue**, or **Blocked** threshold, and clears it when the condition
  ends. The users listed in **MM Watcher Settings** get a realtime toast and
  a notification-bell entry. Thresholds and the recipient list are set in
  that Single DocType; `alerts_enabled` turns the whole thing off.
- **Blocked / idle analysis** in the dashboard drill-down: worked / idle /
  blocked minutes for the day, every alert with its duration, and blocked
  time grouped by reason. Cards flag open alerts; the header shows a total
  open-alert count.
- New DocTypes: `MM Watcher Settings`, `MM Watcher Alert Recipient`,
  `Employee Watcher Alert`.
- Break time is now logged (`Break Start` / `Break End` Work Log events) and
  shown as a KPI in the drill-down alongside worked / idle / blocked.
- The drill-down's activity log has an **All / By work session** toggle so
  each session's events (and a "no work session" bucket for breaks and
  navigation) can be read together.

## 0.3.0 - 2026-09-03

- Remove the Work Section subsystem entirely: `Work Section Master`,
  `Employee Section Session`, and `Employee Section Schedule` DocTypes,
  their tables, all `work_section` / `section_session` fields, the section
  APIs (`start_section`, `end_section`, `extend_section`, `get_my_schedule`),
  the section scheduler jobs, and section columns on every surviving table.
  Migration patch `v0_3_0_remove_sections` drops them on `bench migrate`
  (section history is not migrated).
- The watcher now tracks one flat work session per employee — no section
  to start first.
- Replace the always-on Desk work bar with a small WhatsApp-style floating
  button (bottom-right) carrying a live countdown badge; click it for a
  panel with End Work / Extend / Blocked, or Start Work when idle.
- Opening ERPNext Desk with no active work shows a forced "What work are
  you starting now?" popup that will not close until work is started (or
  the employee marks a break).
- Ending work asks "What did you do / complete?" (required free text) via
  the new `end_work` API, then immediately prompts for the next work.
- Dashboard drops the section column and shows the work description.
- The floating widget loads as a proper `mm_employee_watcher.bundle.js`
  (fixes "frappe is not defined" when it was injected as a raw script), and
  can be minimized to a small edge pill that still shows the live timer
  (remembered per browser).
- While an employee has no active work, the "Start Work" popup now re-appears
  every 2 minutes (BREAK is left alone).
- Every saved document an employee opens on Desk is recorded as a passive
  `Screen Opened` log (`record_screen_view`) — no work-session change.
- Dashboard cards are clickable and carry a **View day** button:
  `get_employee_detail` powers a drill-down showing that employee's whole
  day — every work session (with duration and what they did) and the full
  activity log. Cards are more compact and WORKING/BLOCKED cards show a live
  1-second countdown.
- Widget: robot icon; the side panel now opens/closes purely on the
  `mm-open` class (an earlier `panel.show()` left it stuck open); it docks to
  the right edge.

## 0.2.0 - 2026-09-03

- Add Work Section Master, Employee Section Session, and Employee Section Schedule.
- Enforce one active section per employee and group work sessions inside it.
- Add server-side section countdown, expiry, extension, start/end, and next-work prompt APIs.
- Add an always-visible Desk work bar with section/work timers and Start/End controls.
- Require a description when an employee manually starts Desk work.
- Aggregate Sales Invoice, Payment Entry, and report activity inside the active section.
- Add scheduled-section reminders and mark missed schedules for supervisor review.
- Extend the supervisor dashboard with section, source, reference, timer, and daily activity counts.
- Extend the WMS contract with section lifecycle calls and explicit QR-ready section starts.

## 0.1.0 - 2026-09-03

- Restore the local checkout to the published GitHub `main` history.
- Enforce employee/session ownership on whitelisted mutations.
- Add explicit Paused state and validated session transitions.
- Make expiry notifications one-shot until a session is extended.
- Fix append-only Work Log creation and prevent later edits/deletes.
- Complete linked queue items when their work session is completed.
- Add idempotent WMS reference start/completion and absolute progress APIs.
- Add foreground heartbeat recovery and hide tracking-disabled users.
- Restrict the wall dashboard to dedicated viewer/manager roles.
- Add migration-safe role/custom-field setup and static CI validation.
