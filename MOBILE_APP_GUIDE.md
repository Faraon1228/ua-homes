# 📱 UA Homes - Мобільний Додаток

Це керівництво описує, як упакувати **UA Homes** в мобільні додатки для **Apple Store** та **Google Play**.

---

## 🚀 Три Варіанти Розгортання

### Варіант 1: PWA (Progressive Web App) ✅ НАЙПРОСТІШИЙ

**Переваги:**
- Без потреби в магазинах
- Автоматично оновлюється
- Встановлюється як нативний додаток

**Як встановити на iPhone/iPad:**
1. Відкрити в Safari: https://ua-homes.netlify.app/real-estate-demo.html
2. Нажати "Share" → "Add to Home Screen"
3. Назвати додаток "UA DOM" → "Add"

**Як встановити на Android:**
1. Відкрити в Chrome: https://ua-homes.netlify.app/real-estate-demo.html
2. Нажати меню (три точки) → "Install app"
3. Підтвердити

---

### Варіант 2: Apple Store App (iOS)

**Вимоги:**
- Mac з Xcode
- Apple Developer Account ($99/рік)
- Signing Certificate

**Кроки:**

#### 1. Встановити Capacitor
```bash
cd /Users/vitalii/drive_community.worktrees/real-estate-filtering-feature
npm install -g @capacitor/cli
npm install @capacitor/core @capacitor/app @capacitor/haptics
```

#### 2. Ініціалізувати Capacitor проект
```bash
npx cap init ua-homes "UA Homes - Нерухомість" \
  --web-dir web \
  --ts false
```

#### 3. Додати iOS платформу
```bash
npx cap add ios
npx cap build ios
```

#### 4. Відкрити в Xcode
```bash
open ios/App/App.xcworkspace
```

#### 5. В Xcode:
- Виберіть **App** → **Signing & Capabilities**
- Встановіть **Team** (ваш Apple Developer account)
- Встановіть **Bundle Identifier** (e.g., `com.uadom.realestate`)
- Включіть **Push Notifications** та **Background Modes** якщо потрібно

#### 6. Архівувати та відправити
- Menu: **Product** → **Archive**
- Нажати **Distribute App** → **App Store Connect**
- Слідувати інструкціям

#### 7. В App Store Connect:
- Додати **Screenshots** для кожного пристрою
- Додати **Опис** та **Ключові слова**
- Додати **Рейтинг контенту**
- Отримати **App Review**

---

### Варіант 3: Google Play Store App (Android)

**Вимоги:**
- Android Studio
- Google Play Developer Account ($25 одноразово)
- Signing Keystore

**Кроки:**

#### 1. Встановити Capacitor
```bash
cd /Users/vitalii/drive_community.worktrees/real-estate-filtering-feature
npm install -g @capacitor/cli
npm install @capacitor/core @capacitor/app @capacitor/haptics
```

#### 2. Додати Android платформу
```bash
npx cap add android
npx cap build android
```

#### 3. Відкрити в Android Studio
```bash
open android/
```

#### 4. Встановити підпис (Signing):
- **Build** → **Generate Signed Bundle / APK**
- Створити новий Keystore
  - **Key store path:** `/path/to/ua-homes.jks`
  - **Key store password:** (ваш пароль)
  - **Key alias:** `ua-homes-key`
  - **Key password:** (ваш пароль)
- Вибрати **Bundle (Google Play)**

#### 5. Завантажити в Google Play Console:
- Перейти на https://play.google.com/console
- Створити новий додаток "UA Homes"
- **Налаштування додатка:**
  - **Package name:** `com.uadom.realestate`
  - **Default language:** Українська
  - **App category:** Shopping
- **Загрузити** підписаний AAB файл

#### 6. Заповнити Google Play опис:
- **Стислий опис** (50 символів)
- **Повний опис** (4000 символів)
- **Скріншоти** (min 2, max 8)
- **Іконка програми** (512×512 px)
- **Вибір на банері** (1024×500 px)

#### 7. Додати **Політика конфіденційності** URL
#### 8. Встановити **Рейтинг контенту**
#### 9. Відправити на **Review**

---

## 🎨 Підготовка Іконок

### Генерування всіх потрібних розмірів:

```bash
# Встановити ImageMagick
brew install imagemagick

# Генерувати із базової іконки (512×512)
convert icons/Icon-512.png -resize 192x192 icons/Icon-192.png
convert icons/Icon-512.png -resize 144x144 icons/Icon-144.png
convert icons/Icon-512.png -resize 96x96 icons/Icon-96.png
convert icons/Icon-512.png -resize 72x72 icons/Icon-72.png
convert icons/Icon-512.png -resize 48x48 icons/Icon-48.png

# Для Android (Square)
convert icons/Icon-512.png -resize 512x512 android-icon-512.png
convert icons/Icon-512.png -resize 192x192 android-icon-192.png
```

### Apple Store вимоги:
- **App Icon:** 1024×1024 px (PNG, RGB)
- **App Preview:** 1242×2208 px (MP4, max 30 sec)

### Google Play вимоги:
- **Icon:** 512×512 px (PNG, RGB, квадратна)
- **Feature Graphic:** 1024×500 px (PNG)
- **Screenshots:** 1080×1920 px (PNG/JPG, 2-8 штук)

---

## 📋 Контрольний Список перед відправкою

### Для обох платформ:
- [ ] Тестування на реальному пристрої
- [ ] Перевірка API URL (повинен вказувати на Production Railway)
- [ ] Перевірка дозволів (Geo, Camera, тощо)
- [ ] Перевірка Privacy Policy на сайті
- [ ] Перевірка Terms of Service
- [ ] Оновлення версії (package.json)
- [ ] Тестування інтернет-з'єднання (WiFi + Mobile Data)

### Для Apple Store:
- [ ] Testflight Beta Testing (мінімум 10+ QA тестів)
- [ ] Icloud сумісність перевірена
- [ ] Приватність даних відповідає вимогам Apple
- [ ] Screenshot описи на украї́нській мові

### Для Google Play:
- [ ] Бета тестування в Google Play Console
- [ ] Перевірка політики контенту
- [ ] Перевірка вимог Play Store (відсутність реклами у вибаглива способи)
- [ ] Тестування на пристроях різних Android версій

---

## 🔑 Команди для Оновлення

```bash
# Після змін у коді, оновити на платформах:
npx cap sync ios
npx cap sync android

# Або окремо:
npx cap copy ios
npx cap update ios
```

---

## 📱 Встановлення з QR-кода (для тестування)

```bash
# Генерувати QR код на production URL
npx qrcode https://ua-homes.netlify.app/real-estate-demo.html -o web/qa-homes-qr.png
```

Користувачі можуть сканувати QR код для швидкого встановлення PWA.

---

## 🆚 Порівняння Варіантів

| Функція | PWA | iOS App | Android App |
|---------|-----|---------|-------------|
| Установка | Миттєва | App Store | Play Store |
| Оновлення | Автоматичні | App Store | Play Store |
| Push-сповіщення | Так | Так | Так |
| Offline режим | Так | Так | Так |
| Витрати | $0 | $99/рік | $25 одноразово |
| Час до публікації | Миттєво | 1-3 дні | 2-4 години |
| Обслуговування | Легко | Складно | Складно |

**Рекомендація:** Почніть з **PWA**, потім розгорніть на **App Stores** для більшої видимості.

---

## 🚀 Быстрий Старт для PWA

Ваша PWA вже готова! Просто поділіться цим URL:
```
https://ua-homes.netlify.app/real-estate-demo.html
```

Або сканування QR кода: 
```
web/ua-homes-qr.png
```

**Додаток вже встановлений в браузерах! 📲**
