# Changelog

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
