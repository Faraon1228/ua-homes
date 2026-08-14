package com.uadim.app

import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "com.uadim.app/native"
    private var nativeChannel: MethodChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        nativeChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).apply {
            setMethodCallHandler { call, result ->
                when (call.method) {
                    "getInitialUrl" -> result.success(intent?.dataString)
                    "share" -> {
                        val text = call.argument<String>("text")?.trim().orEmpty()
                        if (text.isEmpty()) {
                            result.error("invalid_share", "Немає посилання для поширення", null)
                            return@setMethodCallHandler
                        }
                        val subject = call.argument<String>("subject")?.trim().orEmpty()
                        val sendIntent = Intent(Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(Intent.EXTRA_TEXT, text)
                            if (subject.isNotEmpty()) putExtra(Intent.EXTRA_SUBJECT, subject)
                        }
                        startActivity(Intent.createChooser(sendIntent, "Поділитися оголошенням"))
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.dataString?.let { nativeChannel?.invokeMethod("openUrl", it) }
    }
}
