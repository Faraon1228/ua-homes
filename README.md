# 🏠 UA Homes — Платформа для пошуку нерухомості в Україні

**UA Homes** — це сучасна PWA платформа для пошуку, фільтрації та аналізу нерухомості в Україні, розроблена для мобільних та веб-браузерів.

## 🚀 Швидкий старт

### Локальний запуск

#### Фронтенд (React)
```bash
cd web
python3 -m http.server 8080
# Відкрийте http://localhost:8080/real-estate-demo.html
```

#### Бекенд (Flask)
```bash
cd backend
pip install -r requirements.txt
python3 app.py
# API запущено на http://localhost:5050
```

## 📱 Функціональність

✅ **Фільтрація нерухомості**
- По місту (Київ, Львів тощо)
- По кількості кімнат
- По площі
- За программою єОселя

✅ **Деталі об'єктів**
- Фотогалерея
- Інтерактивна карта (Leaflet)
- Інформація про розташування
- Рецензії користувачів

✅ **Калькулятор іпотеки**
- Розрахунок з программи єОселя (3% / 7%)
- Вибір кількості років

✅ **Порівняння об'єктів**
- Порівнювати до 3 об'єктів одночасно
- Таблиця характеристик

✅ **Аналітика**
- Графіки розподілу за містами
- Статистика по кімнатам та площі

✅ **Автентифікація**
- Реєстрація / Вхід
- Управління обліковими записами
- Видалення об'єктів (тільки власники)

✅ **PWA (Прогресивна Веб-Додаток)**
- Встановлення як додаток
- Офлайн-режим
- Кеширование статичних ресурсів

## 📱 Окремі мобільні застосунки

- Кореневий Flutter-проєкт — `DriveCommunity`, окремий застосунок лише для
  мотоспільноти: стрічка, історії, чати й профіль. Android application ID:
  `com.drivecommunity.app`; iOS bundle ID: `ua.drivecommunity.app`.
- `apps/ua_dim/` — окремий застосунок `UA-Dim` для пошуку житла та кабінету
  продавця. Він відкриває canonical production UI `ua-dim.com` і не містить
  навігації DriveCommunity.

Обидва застосунки мають окремі Android/iOS збірки та можуть бути встановлені
одночасно.

Android release-збірки підписуються окремими upload keys через локальні
`android/key.properties` і GitHub Actions secrets. Ключі та паролі ігноруються
git. Workflow `Build mobile apps` перевіряє окремо підписані APK обох
застосунків; Google Play release automation буде винесено в окремі workflows.

Workflow `Build UA-Dim iOS store release` збирає лише UA-Dim. Основний режим
використовує cloud-managed signing через App Store Connect API та може після
валідації завантажити IPA у TestFlight. Для нього потрібні GitHub Secrets
`UA_DIM_APP_STORE_CONNECT_ISSUER_ID`, `UA_DIM_APP_STORE_CONNECT_KEY_ID` і
`UA_DIM_APP_STORE_CONNECT_PRIVATE_KEY_BASE64`. API key повинен мати доступ до
Certificates, Identifiers & Profiles. Перед увімкненням
`upload_to_testflight` в App Store Connect має існувати застосунок UA-Dim з
bundle ID `com.uadim.app`. Ручний режим із
`Apple Distribution` certificate та App Store provisioning profile лишається
fallback для збірки IPA без завантаження. Store release DriveCommunity буде
налаштовано окремо пізніше.

Push-сповіщення UA-Dim вмикаються лише коли release workflow отримує Firebase
secrets: `UA_DIM_FIREBASE_API_KEY`, окремі
`UA_DIM_FIREBASE_ANDROID_APP_ID`/`UA_DIM_FIREBASE_IOS_APP_ID`,
`UA_DIM_FIREBASE_MESSAGING_SENDER_ID` і `UA_DIM_FIREBASE_PROJECT_ID`.
Production-доставка з бекенду використовує Firebase Admin credential у Railway:
`UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64` (base64 service-account JSON проєкту
`ua-dim-production`). Якщо credential відсутній, зберігається fallback на
`UA_HOMES_ALERTS_PUSH_WEBHOOK_URL`; webhook не викликається після спроби FCM, щоб
не дублювати сповіщення.
Crash reporting вмикається окремим secret `UA_DIM_SENTRY_DSN`. Без цих значень
застосунок збирається без placeholder-ключів: share, deep links, secure auth та
offline-індикатор працюють, а Firebase/Sentry залишаються вимкненими.

## 🛠️ Архітектура

### Стек технологій

**Фронтенд:**
- React 18+ (без build-системи, vanilla JS)
- Tailwind CSS для стилізації
- Leaflet для карт
- localStorage для зберігання користувача

**Бекенд:**
- Flask (Python)
- SQLite локально / PostgreSQL у production
- JWT для автентифікації
- bcrypt для хешування паролів
- CORS для кросс-доменних запитів
- Redis для shared rate-limit/cache state

**Розгортання:**
- GitHub Actions (CI/CD)
- Netlify public і admin site (`web/`, адмінпанель на `/admin/`)
- Railway (бекенд)

## 📦 Структура проекту

```
ua-homes/
├── web/
│   ├── real-estate-demo.html    # React SPA (960+ рядків)
│   ├── sw.js                     # Service Worker
│   └── ua-homes-manifest.json    # PWA manifest
├── backend/
│   ├── app.py                    # Flask сервер
│   ├── requirements.txt           # Python залежності
│   ├── Procfile                  # Railway config
│   └── railway.toml              # Railway settings
├── scripts/
│   └── build-real-estate-demo.py # Build-time API URL injection
├── lib/                           # DriveCommunity Flutter app
├── android/ і ios/                # DriveCommunity native shells
├── apps/ua_dim/                   # Standalone UA-Dim Flutter app
├── .github/
│   └── workflows/deploy.yml      # GitHub Actions workflow
└── DEPLOYMENT_STEPS.md           # Посібник розгортання
```

## 🔧 Розвиток

### Додавання нових фільтрів

1. Додайте стан у `App()`:
```javascript
const [myFilter, setMyFilter] = useState('default');
```

2. Додайте у логіку фільтрації:
```javascript
const filteredProperties = MOCK_PROPERTIES.filter(item => {
  return matchCity && matchEOselya && (myFilter === 'default' || item.yourProperty === myFilter);
});
```

3. Додайте UI контрол у фільтри-секцію

### Додавання нових об'єктів нерухомості

Відредагуйте `MOCK_PROPERTIES` у `web/real-estate-demo.html`:
```javascript
const MOCK_PROPERTIES = [
  {
    id: 4,
    title: "Нова квартира",
    city: "Київ",
    district: "Шевченківський",
    price: 150000,
    rooms: 2,
    area: 75,
    eOselya: true,
    image: "https://unsplash.com/...",
  },
  // ...
];
```

## 📚 API

### Бекенд endpoints

```
POST   /register              # Реєстрація
POST   /login                 # Вхід
GET    /properties            # Список всіх об'єктів
GET    /properties/<id>       # Деталі об'єкту
DELETE /properties/<id>       # Видалення (JWT)
POST   /reviews               # Додати рецензію
GET    /reviews/<propertyId>  # Рецензії об'єкту
POST   /logout                # Вихід
```

## 🚀 Розгортання

Див. [DEPLOYMENT_STEPS.md](./DEPLOYMENT_STEPS.md) для детальних інструкцій.

**Швидко:**
1. Netlify: publish `web/` як єдиний public/admin deploy
2. Railway: `https://railway.app` → GitHub integration → deploy

Канонічна Netlify-конфігурація: [`netlify.toml`](./netlify.toml). Специфічне
правило `/admin/*` із self-hosted CSP має залишатися окремим від public policy.

## 🔐 Безпека

- Паролі хешуються bcrypt
- JWT токени з 24-годинним терміном дії
- Rate-limiting на бекенді
- CORS обмежені дозволеними origin-ами
- Базові security headers і CSP увімкнені на фронтенді
- Немає чутливих даних у фронтенді

## 📱 Мобільна оптимізація

- 44px touch-цілей
- Responsive дизайн (мобільний-first)
- iOS / Android meta-теги
- PWA для встановлення на домашній екран

## 🆘 Проблемами?

1. **Бекенд не запускається:**
   ```bash
   pip install -r backend/requirements.txt
   python3 backend/app.py
   ```

2. **CORS помилки:**
   Перевірте, що змінні `UA_HOMES_API` та `UA_HOMES_PUBLIC_URL` коректно задані у Netlify/Railway.

3. **Локально не працює пошук:**
   Убедитесь, що бекенд запущено на `http://localhost:5050`

## 📄 Ліцензія

Цей проект розроблено як демонстраційна платформа для пошуку нерухомості в Україні.
