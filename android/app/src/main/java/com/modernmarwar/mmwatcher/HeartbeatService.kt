package com.modernmarwar.mmwatcher

import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Foreground service running the live ~60s heartbeat/status loop while on shift. */
class HeartbeatService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        goForeground(getString(R.string.tracking_active), "Starting…")

        if (!Prefs.isLoggedIn) {
            stopSelf()
            return START_NOT_STICKY
        }

        if (loop == null || loop?.isActive != true) {
            loop = scope.launch { run() }
        }
        return START_STICKY
    }

    private suspend fun run() {
        while (scope.isActive) {
            val status = Heartbeat.runCycle(applicationContext, active = true)
            if (status != null) {
                goForeground(statusTitle(status), statusText(status))
            }
            if (!Prefs.trackingActive) {
                stopSelf()
                return
            }
            delay(60_000)
        }
    }

    private fun statusTitle(s: Watcher.Status): String = when {
        !s.tracking -> "Tracking is disabled for your account"
        s.isWorking -> "WORKING · ${s.activity ?: "work"}"
        s.sessionStatus == "Blocked" -> "BLOCKED · ${s.activity ?: "work"}"
        s.sessionStatus == "Paused" -> "PAUSED · ${s.activity ?: "work"}"
        s.state != null -> s.state
        else -> getString(R.string.tracking_active)
    }

    private fun statusText(s: Watcher.Status): String {
        val end = s.targetEndMs ?: return "No target time set"
        val remainingMin = ((end - Prefs.serverNow()) / 60_000L).toInt()
        return if (remainingMin >= 0) "$remainingMin min left" else "${-remainingMin} min over target"
    }

    private fun goForeground(title: String, text: String) {
        val notification = Notifications.foreground(this, title, text)
        if (Build.VERSION.SDK_INT >= 29) {
            ServiceCompat.startForeground(
                this,
                Notifications.ID_FOREGROUND,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            startForeground(Notifications.ID_FOREGROUND, notification)
        }
    }

    override fun onDestroy() {
        loop?.cancel()
        scope.cancel()
        super.onDestroy()
    }
}
