# Changelog

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
