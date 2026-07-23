# drive_community

DriveCommunity — базовий Flutter додаток для демонстрації карти, stories та профілю.

## Як запустити

1. Перейдіть до каталогу проєкту:
   ```bash
   cd ~/drive_community
   ```
2. Завантажте залежності:
   ```bash
   ~/Downloads/flutter/bin/flutter pub get
   ```
3. Запустіть додаток:
   ```bash
   ~/Downloads/flutter/bin/flutter run
   ```

## Потрібний API ключ Google Maps

Щоб карта відображалася правильно на Android та iOS, потрібно додати Google Maps API ключ.

### 1. Отримайте API ключ

Створіть безкоштовний ключ у [Google Cloud Console](https://console.cloud.google.com/) і увімкніть:

- Google Maps SDK for Android
- Google Maps SDK for iOS

### 2. Додайте ключ для Android

У файл `android/app/src/main/AndroidManifest.xml` додайте всередині тегу `<application>`:

```xml
<meta-data android:name="com.google.android.geo.API_KEY"
           android:value="ВАШ_GOOGLE_MAPS_API_KEY"/>
```

### 3. Додайте ключ для iOS

У файл `ios/Runner/AppDelegate.swift` додайте імпорт Google Maps і надайте свій ключ у методі `didFinishLaunchingWithOptions`:

```swift
import GoogleMaps

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GMSServices.provideAPIKey("ВАШ_IOS_GOOGLE_MAPS_API_KEY")
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
  }
}
```

Альтернативно можна додати ключ у `ios/Runner/Info.plist`:

```xml
<key>GMSApiKey</key>
<string>YOUR_IOS_API_KEY_HERE</string>
```

## Запуск через VS Code

Додано конфігурацію запуску у `./.vscode/launch.json`.

Ви можете вибрати одну з наступних конфігурацій у VS Code:

- `Run DriveCommunity (Flutter)`
- `Profile DriveCommunity (Flutter)`
- `Release DriveCommunity (Flutter)`

## Примітки

- Якщо ви тестуєте у емуляторі / симуляторі, переконайтеся, що пристрій запущено перед `flutter run`.
- Для роботи вибору з галереї на iOS додано дозвіл `NSPhotoLibraryUsageDescription`.
- Історії та чат тепер зберігаються локально у `Hive`, а також можуть синхронізуватися з локальним сервером.
- Додано окрему сторінку “Усі розмови” для перегляду всіх чатів і пошуку.
- Історії можна додавати як фото або відео, а відео відтворюються у переглядачі історій.
- Код розбитий на моделі, сервіси, стани та екрани, щоб краще підтримувати подальший розвиток.

## Сервер синхронізації

Щоб використовувати реальну серверну синхронізацію, запустіть локальний бекенд у папці `server`:

```bash
cd ~/drive_community/server
dart pub get
dart run bin/server.dart
```

Після цього додаток автоматично спробує підключитися до сервера на:

- iOS симулятор: `http://localhost:8080`
- Android емултор: `http://10.0.2.2:8080`

Сервер зберігає історії та чат-потоки у файлі `server/storage.json` і повертає їх для синхронізації.
