# 🚀 Етапи розгортання UA Homes

Ваша платформа готова до production! Слідуйте цим простим кроками для повного запуску.

## ✅ Готово до деплою

- [x] Фронтенд зібраний (`web/real-estate-demo.html`)
- [x] Бекенд готовий (`backend/app.py`)
- [x] GitHub Actions workflow налаштований (`.github/workflows/deploy.yml`)
- [x] GitHub репозиторій: https://github.com/Vitaliy-spd/ua-homes

---

## 📋 Крок 1: Налаштування Netlify (фронтенд)

### Швидко (5 хвилин):

1. Перейдіть на https://app.netlify.com
2. **"New site from Git"** → **GitHub** → авторизуйте
3. Виберіть **`Vitaliy-spd/ua-homes`**
4. Налаштування:
   ```
   Branch:         agents/real-estate-filtering-feature
   Build command:  python3 scripts/build-real-estate-demo.py
   Publish dir:    web
   ```
5. **Deploy site**

### Налаштування змінної (後):

Після деплою Railway:
1. На сайті Netlify: **Site settings** → **Build & deploy** → **Environment**
2. Додайте змінну:
   ```
   Name:  UA_HOMES_API
   Value: https://ua-homes-XXXXX.up.railway.app
   ```
3. Перетригеріть деплой: **Deploys** → **Trigger deploy**

---

## 🚂 Крок 2: Налаштування Railway (бекенд)

### Автоматичний деплой з GitHub:

1. Перейдіть на https://railway.app
2. Відкрийте ваш проект `ua-homes`
3. Перейдіть в **GitHub** (або шукайте інтеграцію)
4. **Connect GitHub** → авторизуйте
5. Виберіть репозиторій `Vitaliy-spd/ua-homes`
6. Виберіть папку: `backend`
7. **Deploy**

### Налаштування змінних:

На сторінці сервісу в Railway:
1. **Variables** → додайте:
   ```
   UA_HOMES_SECRET = ваш-секретний-ключ
   DATABASE_URL   = postgres://...
   REDIS_URL      = redis://...
   ```
2. Railway автоматично спалює код при push до `agents/real-estate-filtering-feature`

### Отримання URL бекенду:

1. На сторінці сервісу: **Settings** → знайдіть **Railway Provided Domain**
2. Скопіюйте URL (наприклад: `https://ua-homes-abc123.up.railway.app`)
3. Використайте його в Netlify (див. вище)

---

## 🔄 Крок 3: Налаштування бази даних і Redis

Railway має вбудовану PostgreSQL і Redis.

**Поточно використовується:** SQLite локально, PostgreSQL у production.

Щоб використовувати PostgreSQL на Railway:
1. На панелі Railway: **Add service** → **PostgreSQL**
2. Скопіюйте `DATABASE_URL` у Variables бекенд-сервісу
3. Додайте Redis service і скопіюйте `REDIS_URL`
4. Перезапустіть backend

---

## 📱 Крок 4: Налаштування домену (опціонально)

### Netlify:
- Site settings → **Domain management** → купіть або підключіть домен

### Railway:
- Settings → **Custom domain** → введіть домен

### Split deploys:
- public сайт публікуйте з [web/](/Users/vitalii/drive_community.worktrees/real-estate-filtering-feature/web)
- admin сайт публікуйте з [web/admin/](/Users/vitalii/drive_community.worktrees/real-estate-filtering-feature/web/admin)
- backend має окремий Railway service з `DATABASE_URL` і `REDIS_URL`

---

## 🔐 Secrets в GitHub

Все налаштовано. GitHub Actions використовує:
- `RAILWAY_TOKEN` ✅
- `RAILWAY_PROJECT_ID` ✅
- `RAILWAY_SERVICE_ID` ✅
- `NETLIFY_AUTH_TOKEN` (опціонально, якщо автоматичний деплой)
- `NETLIFY_SITE_ID` (опціонально)
- `UA_HOMES_API` (встановити після Railway)

---

## 🧪 Тестування

### Локально:

```bash
# Фронтенд
cd web
python3 -m http.server 8080

# Бекенд
cd backend
python3 app.py
```

### Після деплою:

1. Відкрийте URL Netlify
2. Перевірте функціональність
3. Логіка фільтрації, купівлі, картки повинні працювати

---

## 🆘 Проблеми?

### Фронтенд не підключується до бекенду:
- Перевірте, що `UA_HOMES_API` змінна правильна на Netlify
- Переглядайте Browser Console (F12) на помилки CORS

### Railway сервіс не запускається:
- Перевірте логи на Railway dashboard
- Переконайтеся, що `backend/requirements.txt` має усі залежності
- Переконайтеся, що `DATABASE_URL` і `REDIS_URL` задані для production

### Git push не тригерує деплой:
- Railway webhook повинен бути налаштований автоматично
- Перевірте GitHub Integrations на Railway

---

## 📊 Архітектура

```
GitHub (Vitaliy-spd/ua-homes)
    ↓
GitHub Actions Workflow
    ├→ Netlify public + admin
    └→ Railway (бекенд)
```

При кожному `git push agents/real-estate-filtering-feature`:
1. GitHub Actions запускає build
2. Фронтенд розгортається на Netlify
3. Бекенд розгортається на Railway

---

## 🎉 Готово!

Ваша платформа активна. Користувачі можуть відвідувати Netlify URL і взаємодіяти з вашою платформою UA Homes!

**Дякуємо за використання UA Homes! 🚀**
