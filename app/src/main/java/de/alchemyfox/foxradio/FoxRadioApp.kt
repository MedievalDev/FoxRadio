package de.alchemyfox.foxradio

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class FoxRadioApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel(
            PlaybackService.CHANNEL_ID,
            getString(R.string.notif_channel_name),
            NotificationManager.IMPORTANCE_LOW
        ).apply { description = getString(R.string.notif_channel_desc) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }
}
