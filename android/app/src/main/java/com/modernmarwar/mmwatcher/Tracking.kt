package com.modernmarwar.mmwatcher

import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * Owns the two background pieces:
 *  - [HeartbeatService]: a foreground service with the ~60s live loop.
 *  - [HeartbeatWorker]: a 15-minute WorkManager backstop so the employee never
 *    silently flips OFFLINE (10 min server cutoff) if the OS kills the service.
 */
object Tracking {

    private const val WORK_NAME = "mm-heartbeat"

    fun start(context: Context) {
        Prefs.trackingActive = true
        val intent = Intent(context, HeartbeatService::class.java)
        ContextCompat.startForegroundService(context, intent)
        enqueueWorker(context)
    }

    fun stop(context: Context) {
        Prefs.trackingActive = false
        context.stopService(Intent(context, HeartbeatService::class.java))
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        Notifications.cancel(context, Notifications.ID_FOREGROUND)
    }

    /** Called from BootReceiver / MainActivity to resume after a restart. */
    fun resumeIfActive(context: Context) {
        if (Prefs.trackingActive && Prefs.isLoggedIn) start(context)
    }

    private fun enqueueWorker(context: Context) {
        val request = PeriodicWorkRequestBuilder<HeartbeatWorker>(15, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME,
            if (Build.VERSION.SDK_INT >= 31) {
                ExistingPeriodicWorkPolicy.UPDATE
            } else {
                ExistingPeriodicWorkPolicy.KEEP
            },
            request,
        )
    }
}
