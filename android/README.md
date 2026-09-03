# MM Work Tracker — Android app

A thin native client for the `mm_employee_watcher` backend. It signs the
employee into their Frappe/ERPNext site and calls the same whitelisted API the
Desk floating widget uses (`start_work`, `end_work`, `extend_work`,
`mark_blocked`, `mark_break`, `resume_work`, `heartbeat`, `get_my_status`,
`get_next_work`), so a warehouse/field employee shows up live on
`/mm_dashboard` without opening Desk.

## What it does

- **Sign in** with the site URL + ERPNext username/password (session cookie,
  stored on device). Works against any site.
- **Status screen** — current state (WORKING / IDLE / BREAK / BLOCKED /
  OFFLINE), current activity, description, a live countdown to target time,
  and qty done / target.
- **Work controls** — Start Work (activity picker + description + duration +
  target qty), End Work ("what did you do?" + completed qty), +15m / +30m,
  Mark Blocked, Resume, I'm on a break.
- **Background heartbeat** — a foreground service pings `heartbeat` every ~60s
  so the employee never silently flips OFFLINE (server cutoff is 10 min). A
  15-minute `WorkManager` job is a backstop if the OS kills the service.
- **Over-target alert** — when a session passes its target time the app raises
  a high-priority notification with **Done / +30 min / Blocked** actions
  (Done and Blocked take a typed note inline). Polled from `get_my_status`;
  there is no server-side FCM push yet.
- **Auto-chain** — after End Work, if the backend auto-started the next
  `Employee Work Queue` item (or one is pending) the app says so.

## Build

No Android Studio needed — GitHub Actions builds the APK
(`.github/workflows/android.yml`):

- Every push to `main` that touches `android/**` builds a **debug-signed APK**,
  uploads it as a workflow artifact, and refreshes the `android-latest`
  GitHub Release. Download `mm-work-tracker-debug.apk` from the run's
  **Artifacts** or from **Releases → android-latest**.
- Or trigger it manually from the **Actions** tab ("Android APK" →
  *Run workflow*).

### Local build

```bash
cd android
gradle wrapper --gradle-version 8.7   # first time only, creates ./gradlew
./gradlew assembleDebug
# APK at app/build/outputs/apk/debug/app-debug.apk
```

Or just open the `android/` folder in Android Studio (Giraffe+), let it sync,
and Run.

## Install on a device

1. Copy the APK to the phone (or download it from the Releases page in the
   phone's browser).
2. Allow "install unknown apps" for that browser / file manager when prompted.
3. Open the app, enter the site URL and your login.
4. Grant the **notifications** permission, and use the overflow menu →
   **Fix background limits** to exempt the app from battery optimisation
   (needed on most OEM Android builds for reliable heartbeats).

The APK is debug-signed — fine for internal side-loading. For Play Store or
managed (MDM) distribution, add a release keystore and a `release` signing
config, then build `assembleRelease`.

## Config / assumptions

- The device clock's time zone should match the site's; the countdown corrects
  for clock skew via `heartbeat`'s `server_time` but not for a tz mismatch.
- The signed-in User needs a linked **Employee** (`Employee.user_id`) and
  **Enable Work Tracking** checked, exactly like the Desk widget.
- `usesCleartextTraffic` is on so a plain-`http://` dev site works; use
  `https://` in production.
