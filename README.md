# 🐉 Telegram Dragon Lair Bot & 3D Mini App (24/7 Free Hosting)

Повний готовий пакет для безкоштовного запуску Telegram-бота та 3D WebApp у хмарі 24/7.

## 📁 Структура проєкту:
- `index.html` — Оптимізоване 3D-лігво драконів (Three.js, 4 стихії, 360° панорами, скелетні анімації, інтерактив) із хмарною синхронізацією Telegram.
- `main.py` — Швидкий веб-сервер FastAPI, що роздає 3D WebApp та запускає бота.
- `bot.py` — Telegram-бот (Aiogram 3): команди `!моє лігво`, `!рулетка`, ігри `!бомба`, `!фільм`, `!профіль`.
- `database.py` — База даних SQLite для збереження балансу монет, їжі, яєць, рівнів і імен драконів.
- `requirements.txt` — Необхідні бібліотеки Python.
- `Procfile` та `render.yaml` — Конфігурації для автоматичного розгортання на Render.com.

## 🚀 Покроковий запуск за 5 хвилин:

### Крок 1: Отримання токена бота в Telegram
1. Відкрийте бота **[@BotFather](https://t.me/BotFather)** у Telegram.
2. Надішліть команду `/newbot`.
3. Введіть назву (наприклад, `Лігво Дракона`) та юзернейм бота (наприклад, `MyDragonLair_bot`).
4. Скопіюйте отриманий **HTTP API Token**.

### Крок 2: Завантаження на GitHub
1. Перейдіть на **[github.com](https://github.com)** та створіть новий репозиторій (наприклад, `dragon-lair-bot`).
2. Завантажте всі файли з цієї папки до репозиторію.

### Крок 3: Запуск на Render.com (Безкоштовно 24/7)
1. Зареєструйтесь на **[render.com](https://render.com)** (можна в 1 клік через GitHub).
2. Натисніть кнопку **New +** -> **Web Service**.
3. Оберіть ваш створений репозиторій з GitHub.
4. Render автоматично підтягне налаштування:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** `Free`
5. Гортайте вниз до розділу **Environment Variables** (Змінні оточення) та додайте:
   - `BOT_TOKEN` = `ваш_токен_від_botfather`
   - `WEBAPP_URL` = `https://назва-вашого-сервісу.onrender.com` (назву ви вказуєте зверху)
6. Натисніть **Deploy Web Service**! За 1-2 хвилини бот запуститься.

### Крок 4: Підключення 3D-кнопки меню в Telegram
1. Знову відкрийте **[@BotFather](https://t.me/BotFather)**.
2. Надішліть команду `/setmenubutton`.
3. Оберіть вашого бота.
4. Надішліть посилання вашого сайту з Render (наприклад, `https://dragon-lair.onrender.com`).
5. Введіть назву для кнопки меню: `🐉 Моє Лігво`.

### Крок 5: Щоб бот ніколи не засинав (24/7)
1. Відкрийте безкоштовний сервіс **[cron-job.org](https://cron-job.org)** або **[uptimerobot.com](https://uptimerobot.com)**.
2. Додайте посилання: `https://назва-вашого-сервісу.onrender.com/health` кожні 10 хвилин.
3. Готово! Ваш бот працює цілодобово 24/7 безкоштовно!
