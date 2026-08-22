import Flutter
import FirebaseCore
import FirebaseMessaging
import PhotosUI
import UIKit
import UniformTypeIdentifiers

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var pendingPhotoPickerResult: FlutterResult?
  private var pendingPhotoProviders: [NSItemProvider] = []
  private var isReadingPhoto = false
  private var apnsDeviceToken: Data?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let launched = super.application(
      application,
      didFinishLaunchingWithOptions: launchOptions
    )
    application.registerForRemoteNotifications()
    return launched
  }

  override func application(
    _ application: UIApplication,
    didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
  ) {
    apnsDeviceToken = deviceToken
    if FirebaseApp.app() != nil {
      Messaging.messaging().apnsToken = deviceToken
    }
    super.application(
      application,
      didRegisterForRemoteNotificationsWithDeviceToken: deviceToken
    )
  }

  private func syncPushRegistration() -> Bool {
    guard let apnsDeviceToken else {
      UIApplication.shared.registerForRemoteNotifications()
      return false
    }
    Messaging.messaging().apnsToken = apnsDeviceToken
    return true
  }

  override func application(
    _ application: UIApplication,
    didFailToRegisterForRemoteNotificationsWithError error: Error
  ) {
    super.application(
      application,
      didFailToRegisterForRemoteNotificationsWithError: error
    )
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    let channel = FlutterMethodChannel(
      name: "com.uadim.app/native",
      binaryMessenger: engineBridge.applicationRegistrar.messenger()
    )
    channel.setMethodCallHandler { [weak self] call, result in
      if call.method == "syncPushRegistration" {
        result(self?.syncPushRegistration() ?? false)
        return
      }
      if call.method == "supportsPhotoPicker" {
        if #available(iOS 14.5, *) {
          result(true)
        } else {
          result(false)
        }
        return
      }
      guard #available(iOS 14.5, *) else {
        result(FlutterError(
          code: "picker_unavailable",
          message: "Фототека доступна починаючи з iOS 14.5",
          details: nil
        ))
        return
      }
      switch call.method {
      case "pickPhotos":
        self?.presentPhotoPicker(call: call, result: result)
      case "readNextPhoto":
        self?.readNextPhoto(result: result)
      case "resetPhotoPicker":
        let pendingResult = self?.pendingPhotoPickerResult
        self?.pendingPhotoPickerResult = nil
        self?.pendingPhotoProviders.removeAll()
        pendingResult?(0)
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  @available(iOS 14.5, *)
  private func presentPhotoPicker(call: FlutterMethodCall, result: @escaping FlutterResult) {
    guard pendingPhotoPickerResult == nil,
          pendingPhotoProviders.isEmpty,
          !isReadingPhoto else {
      result(FlutterError(code: "picker_busy", message: "Вибір фото вже відкритий", details: nil))
      return
    }
    guard let presenter = topViewController() else {
      result(FlutterError(code: "picker_unavailable", message: "Не вдалося відкрити фототеку", details: nil))
      return
    }

    let arguments = call.arguments as? [String: Any]
    let allowMultiple = arguments?["allowMultiple"] as? Bool ?? false
    var configuration = PHPickerConfiguration(photoLibrary: .shared())
    configuration.filter = .images
    configuration.selectionLimit = allowMultiple ? 8 : 1

    let picker = PHPickerViewController(configuration: configuration)
    picker.delegate = self
    pendingPhotoPickerResult = result
    presenter.present(picker, animated: true)
  }

  @available(iOS 14.5, *)
  private func readNextPhoto(result: @escaping FlutterResult) {
    guard !isReadingPhoto else {
      result(FlutterError(code: "picker_busy", message: "Попереднє фото ще обробляється", details: nil))
      return
    }
    guard !pendingPhotoProviders.isEmpty else {
      result(nil)
      return
    }
    let provider = pendingPhotoProviders.removeFirst()
    guard let typeIdentifier = provider.registeredTypeIdentifiers.first(
      where: { UTType($0)?.conforms(to: .image) == true }
    ) else {
      result(["error": "Непідтримуваний формат фото"])
      return
    }
    isReadingPhoto = true
    provider.loadDataRepresentation(forTypeIdentifier: typeIdentifier) { data, _ in
      guard let data else {
        DispatchQueue.main.async {
          self.isReadingPhoto = false
          result(["error": "Не вдалося прочитати фото"])
        }
        return
      }
      guard data.count <= 10_485_760 else {
        DispatchQueue.main.async {
          self.isReadingPhoto = false
          result(["error": "Фото перевищує дозволені 10 МБ"])
        }
        return
      }
      let contentType = UTType(typeIdentifier)
      let fileExtension = contentType?.preferredFilenameExtension ?? "jpg"
      let suggestedName = provider.suggestedName?
        .trimmingCharacters(in: .whitespacesAndNewlines)
      let baseName = suggestedName?.isEmpty == false ? suggestedName! : "ua-dim-photo"
      let fileName = (baseName as NSString).pathExtension.isEmpty
        ? "\(baseName).\(fileExtension)"
        : baseName
      DispatchQueue.main.async {
        self.isReadingPhoto = false
        result([
          "name": fileName,
          "type": contentType?.preferredMIMEType ?? "image/jpeg",
          "data": FlutterStandardTypedData(bytes: data),
        ])
      }
    }
  }

  private func topViewController() -> UIViewController? {
    let scene = UIApplication.shared.connectedScenes
      .compactMap { $0 as? UIWindowScene }
      .first { $0.activationState == .foregroundActive }
    var controller = scene?.windows.first { $0.isKeyWindow }?.rootViewController
    while let presented = controller?.presentedViewController {
      controller = presented
    }
    return controller
  }
}

@available(iOS 14.5, *)
extension AppDelegate: PHPickerViewControllerDelegate {
  func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
    picker.dismiss(animated: true)
    guard let callback = pendingPhotoPickerResult else { return }
    pendingPhotoPickerResult = nil
    pendingPhotoProviders = results.map(\.itemProvider)
    callback(pendingPhotoProviders.count)
  }
}
