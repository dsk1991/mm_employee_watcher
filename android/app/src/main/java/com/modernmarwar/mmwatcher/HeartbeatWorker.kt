package com.modernmarwar.mmwatcher

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters

/**
 * 15-minute backstop. The server marks an employee OFFLINE after 10 minutes
 * without a heartbeat, so this keeps them "online" (and fires the over-target
 * alert within ~15 min) even when the foreground service has been killed.
 */
class HeartbeatWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        if (!Prefs.trackingActive || !Prefs.isLoggedIn) return Result.success()
        Heartbeat.runCycle(applicationContext, active = true)
        return Result.success()
    }
}
