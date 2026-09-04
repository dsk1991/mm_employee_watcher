# Changelog

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
