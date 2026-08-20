package com.uadim.app

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.IOException

class MainActivity : FlutterActivity() {
    private val channelName = "com.uadim.app/native"
    private val filePickerRequestCode = 4201
    private var nativeChannel: MethodChannel? = null
    private var pendingFileResult: MethodChannel.Result? = null
    private var pendingCameraUri: Uri? = null
    private var pendingCameraFile: File? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        purgeStaleCameraFiles()
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
                    "pickFiles" -> openFileChooser(call, result)
                    else -> result.notImplemented()
                }
            }
        }
    }

    private fun openFileChooser(call: io.flutter.plugin.common.MethodCall, result: MethodChannel.Result) {
        if (pendingFileResult != null) {
            result.error("picker_busy", "Вибір файлу вже відкритий", null)
            return
        }

        val mimeTypes = call.argument<List<String>>("acceptTypes")
            .orEmpty()
            .flatMap { it.split(",") }
            .map { it.trim().lowercase() }
            .filter { it.contains("/") }
            .distinct()
        val allowMultiple = call.argument<Boolean>("allowMultiple") == true
        val capture = call.argument<Boolean>("capture") == true
        val acceptsImages = mimeTypes.isEmpty() ||
            mimeTypes.any { it == "*/*" || it.startsWith("image/") }

        val galleryIntent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = if (mimeTypes.size == 1) mimeTypes.first() else "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, allowMultiple)
            if (mimeTypes.size > 1) {
                putExtra(Intent.EXTRA_MIME_TYPES, mimeTypes.toTypedArray())
            }
        }
        val cameraIntent = if (acceptsImages && capture) createCameraIntent() else null
        val pickerIntent = if (capture && cameraIntent != null) {
            cameraIntent
        } else {
            Intent.createChooser(
                galleryIntent,
                if (acceptsImages) "Обрати фото з фототеки" else "Обрати медіафайл",
            )
        }

        pendingFileResult = result
        try {
            startActivityForResult(pickerIntent, filePickerRequestCode)
        } catch (_: ActivityNotFoundException) {
            clearPendingCameraFile()
            pendingFileResult = null
            result.error("picker_unavailable", "На пристрої немає доступного вибору файлів", null)
        }
    }

    private fun createCameraIntent(): Intent? {
        val cameraIntent = Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE)
        if (cameraIntent.resolveActivity(packageManager) == null) return null

        val cameraFile: File
        val cameraUri: Uri
        try {
            cameraFile = File.createTempFile("ua_dim_", ".jpg", cacheDir)
            cameraUri = FileProvider.getUriForFile(
                this,
                "$packageName.fileprovider",
                cameraFile,
            )
        } catch (_: IOException) {
            return null
        } catch (_: IllegalArgumentException) {
            return null
        }
        pendingCameraFile = cameraFile
        pendingCameraUri = cameraUri
        return cameraIntent.apply {
            putExtra(android.provider.MediaStore.EXTRA_OUTPUT, cameraUri)
            clipData = ClipData.newRawUri("UA-Dim photo", cameraUri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        }
    }

    @Deprecated("Required by the Android file chooser bridge")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != filePickerRequestCode) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }

        val result = pendingFileResult
        pendingFileResult = null
        if (result == null) {
            clearPendingCameraFile()
            return
        }

        val selectedUris = mutableListOf<Uri>()
        if (resultCode == Activity.RESULT_OK) {
            data?.clipData?.let { selected ->
                for (index in 0 until selected.itemCount) {
                    selectedUris.add(selected.getItemAt(index).uri)
                }
            }
            data?.data?.let { selectedUris.add(it) }
            if (selectedUris.isEmpty() && pendingCameraFile?.length()?.let { it > 0 } == true) {
                pendingCameraUri?.let { selectedUris.add(it) }
            }
        }

        val usedCameraFile = selectedUris.contains(pendingCameraUri)
        if (!usedCameraFile) {
            clearPendingCameraFile()
        } else {
            val capturedFile = pendingCameraFile
            clearPendingCameraState()
            Handler(Looper.getMainLooper()).postDelayed(
                { capturedFile?.delete() },
                cameraCleanupDelayMillis,
            )
        }
        result.success(selectedUris.distinct().map(Uri::toString))
    }

    private fun purgeStaleCameraFiles() {
        val cutoff = System.currentTimeMillis() - cameraCleanupDelayMillis
        cacheDir.listFiles { file ->
            file.isFile && file.name.startsWith("ua_dim_") && file.name.endsWith(".jpg")
        }?.forEach { file ->
            if (file.lastModified() < cutoff) file.delete()
        }
    }

    private fun clearPendingCameraFile() {
        pendingCameraFile?.delete()
        clearPendingCameraState()
    }

    private fun clearPendingCameraState() {
        pendingCameraFile = null
        pendingCameraUri = null
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.dataString?.let { nativeChannel?.invokeMethod("openUrl", it) }
    }

    companion object {
        private const val cameraCleanupDelayMillis = 30 * 60 * 1000L
    }
}
