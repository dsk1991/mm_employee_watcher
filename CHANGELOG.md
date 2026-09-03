# Changelog

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
  can be minimized to a thin edge sliver (remembered per browser).

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
