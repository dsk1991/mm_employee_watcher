package com.modernmarwar.mmwatcher

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Prefs.init(this)
        Notifications.createChannels(this)
    }
}
