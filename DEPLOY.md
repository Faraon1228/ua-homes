# UA Homes — Деплой в продакшн

## Архітектура

```
Фронтенд (HTML/React) → Netlify або Vercel (безкоштовно)
Бекенд (Flask/Python)  → Railway або Render (безкоштовно)
База даних             → SQLite (вбудована у бекенд)
Домен (опційно)        → ua-homes.com.ua (~300 грн/рік)
```

---

## 🚀 Крок 1 — Бекенд на Railway (5 хвилин)

### 1.1 Підготовка
```bash
# Перейдіть на https://railway.app
# Зареєструйтесь через GitHub
```

### 1.2 Деплой
1. **New Project** → **Deploy from GitHub repo**
2. Оберіть цей репозиторій
3. Railway автоматично знайде `/backend` папку
4. Додайте змінну середовища:
   - `UA_HOMES_SECRET` = будь-який довгий рядок (наприклад: `openssl rand -hex 32`)
5. Натисніть **Deploy**

### 1.3 Отримайте URL
Після деплою Railway дасть URL: `https://ua-homes-production.railway.app`

> ⚠️ Скопіюйте цей URL — він потрібен для фронтенду

---

## 🌐 Крок 2 — Фронтенд на Netlify (3 хвилини)

### 2.1 Деплой
1. **https://netlify.com** → **Add new site** → **Import from Git**
2. Оберіть цей репозиторій
3. Build command: (залишити порожнім)
4. Publish directory: `web`
5. Додайте змінну середовища:
   - `UA_HOMES_API` = ваш Railway URL з кроку 1.3

### 2.2 Налаштування API URL
У Netlify → Site settings → Environment variables:
```
UA_HOMES_API = https://ua-homes-production.railway.app
```

Netlify дасть URL: `https://ua-homes.netlify.app`

---

## 🔗 Крок 3 — Власний домен (опційно)

### Купити домен
- **nic.ua** — `ua-homes.com.ua` ≈ 300 грн/рік
- **namecheap.com** — `ua-homes.com` ≈ $10/рік

### Підключити до Netlify
1. Netlify → Domain settings → Add custom domain
2. У реєстратора: додайте DNS запис:
   ```
   CNAME  @  ua-homes.netlify.app
   ```
3. SSL-сертифікат автоматично (Let's Encrypt)

---

## 🔄 Автоматичні оновлення

Після налаштування — **будь-який `git push` автоматично:**
1. Netlify перебудовує фронтенд (< 1 хв)
2. Railway перезапускає бекенд (< 2 хв)

```bash
# Оновлення оголошень або коду
git add -A
git commit -m "feat: ..."
git push origin main
# Через 2 хвилини зміни онлайн
```

---

## 💰 Вартість

| Сервіс | Безкоштовно | Платно |
|--------|-------------|--------|
| Netlify | 100 GB/міс трафік | $19/міс (більше) |
| Railway | $5 кредитів/міс | $20/міс (більше) |
| Домен .com.ua | — | ~300 грн/рік |
| **Разом старт** | **$0** | — |

---

## 📱 PWA — Встановлення як додаток

Після деплою ваш сайт можна встановити як нативний додаток:

**iOS Safari:**
Поділитись (□↑) → Додати на початковий екран

**Android Chrome:**
Меню ⋮ → Додати на головний екран
(або Chrome автоматично запропонує банер)

---

## 🛡️ Безпека продакшн

Обов'язково встановіть ці env змінні на Railway:
```bash
UA_HOMES_SECRET=<мінімум 64 символи hex>  # jwt secret
# Генерація: python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 📊 Моніторинг

- **Railway** — вбудовані логи + метрики CPU/RAM
- **Netlify** — аналітика трафіку (Netlify Analytics)
- **UptimeRobot** (безкоштовно) — ping кожні 5 хв, сповіщення на email

---

## 🔧 Локальний запуск (для розробки)

```bash
# Бекенд
cd backend
pip3 install -r requirements.txt
python3 app.py
# → http://localhost:5050

# Фронтенд
cd web
python3 -m http.server 8080
# → http://localhost:8080/real-estate-demo.html
```
