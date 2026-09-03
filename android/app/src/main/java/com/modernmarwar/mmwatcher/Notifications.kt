package com.modernmarwar.mmwatcher

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.RemoteInput

object Notifications {

    const val CHANNEL_TRACKING = "tracking"
    const val CHANNEL_ALERTS = "alerts"

    const val ID_FOREGROUND = 1
    const val ID_EXPIRY = 2
    const val ID_ERROR = 3

    const val REMOTE_KEY = "text"

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_TRACKING,
                context.getString(R.string.channel_tracking_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = context.getString(R.string.channel_tracking_desc) },
        )
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERTS,
                context.getString(R.string.channel_alerts_name),
                NotificationManager.IMPORTANCE_HIGH,
            ).apply { description = context.getString(R.string.channel_alerts_desc) },
        )
    }

    fun foreground(context: Context, title: String, text: String): Notification {
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stop = PendingIntent.getBroadcast(
            context, 10,
            Intent(context, ActionReceiver::class.java).setAction(ActionReceiver.ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(context, CHANNEL_TRACKING)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(0, context.getString(R.string.stop_tracking), stop)
            .build()
    }

    fun expiry(context: Context, session: String, activity: String?) {
        fun action(name: String, id: Int, withInput: Boolean): NotificationCompat.Action {
            val intent = Intent(context, ActionReceiver::class.java)
                .setAction(name)
                .putExtra(ActionReceiver.EXTRA_SESSION, session)
            val pi = PendingIntent.getBroadcast(
                context, id, intent,
                PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val builder = NotificationCompat.Action.Builder(0, label(name), pi)
            if (withInput) {
                builder.addRemoteInput(
                    RemoteInput.Builder(REMOTE_KEY)
                        .setLabel(if (name == ActionReceiver.ACTION_END) "What did you do?" else "Reason")
                        .build(),
                )
            }
            return builder.build()
        }

        val notif = NotificationCompat.Builder(context, CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("Time is up" + (activity?.let { " · $it" } ?: ""))
            .setContentText("Mark it done, extend, or flag it blocked.")
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(
                PendingIntent.getActivity(
                    context, 20, Intent(context, MainActivity::class.java),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
            .addAction(action(ActionReceiver.ACTION_END, 21, withInput = true))
            .addAction(action(ActionReceiver.ACTION_EXTEND, 22, withInput = false))
            .addAction(action(ActionReceiver.ACTION_BLOCK, 23, withInput = true))
            .build()
        notifyIfAllowed(context, ID_EXPIRY, notif)
    }

    fun error(context: Context, title: String, text: String) {
        val notif = NotificationCompat.Builder(context, CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .build()
        notifyIfAllowed(context, ID_ERROR, notif)
    }

    fun cancel(context: Context, id: Int) = NotificationManagerCompat.from(context).cancel(id)

    private fun label(action: String) = when (action) {
        ActionReceiver.ACTION_END -> "Done"
        ActionReceiver.ACTION_EXTEND -> "+30 min"
        ActionReceiver.ACTION_BLOCK -> "Blocked"
        else -> action
    }

    private fun notifyIfAllowed(context: Context, id: Int, notification: Notification) {
        val nm = NotificationManagerCompat.from(context)
        if (nm.areNotificationsEnabled()) {
            try {
                nm.notify(id, notification)
            } catch (e: SecurityException) {
                // POST_NOTIFICATIONS not granted; nothing else to do.
            }
        }
    }
}
