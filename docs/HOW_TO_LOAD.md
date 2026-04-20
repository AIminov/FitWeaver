# Как загрузить тренировки на часы Garmin / How to Load Workouts onto Your Garmin Watch

---

## Русский

### Вариант А — USB (без приложений)

1. Подключите часы к компьютеру кабелем USB
2. Часы появятся как съёмный накопитель в проводнике
3. Откройте ZIP-архив, который прислал бот
4. Скопируйте `.fit` файлы в папку на часах:
   ```
   Garmin / NewFiles /
   ```
5. Безопасно извлеките часы — тренировки появятся в меню **«Тренировки»**

> **Примечание:** некоторые модели часов могут не отображаться как накопитель автоматически — в этом случае используйте Garmin Express (см. ниже).

---

### Вариант Б — Garmin Express (компьютер + USB)

[Garmin Express](https://www.garmin.com/ru-RU/software/express/) — официальное приложение для синхронизации часов с компьютером.

1. Скачайте и установите Garmin Express с **garmin.com/express**
2. Подключите часы кабелем USB
3. Добавьте устройство в Garmin Express
4. Откройте вкладку **«Тренировки»** и импортируйте `.fit` файлы
5. Нажмите **«Синхронизировать»**

---

### Вариант В — Garmin Calendar (без USB, через приложение)

Самый удобный способ — тренировки загружаются напрямую в ваш аккаунт Garmin Connect.

**Требования:** аккаунт Garmin Connect (бесплатно на connect.garmin.com)

**Как это работает:**
1. В боте: `/connect_garmin` — войдите в Garmin Connect (email + пароль)
   - Пароль используется только библиотекой-загрузчиком для получения токена
   - Токен кешируется локально, пароль не сохраняется
2. Соберите план: отправьте текст → `/build`
3. В диалоге доставки выберите **📅 Загрузить в Garmin Calendar**
4. Откройте приложение **Garmin Connect** на телефоне → нажмите «Синхронизировать»
5. Тренировки появятся на часах в разделе **«Тренировки»** → **«Запланированные»**

> **Совет:** после первого входа повторная авторизация не требуется — токен сохранён.

---

## English

### Option A — USB (no extra software)

1. Connect your watch to your computer with a USB cable
2. The watch appears as a removable drive in File Explorer / Finder
3. Unzip the archive you received from the bot
4. Copy the `.fit` files into this folder on the watch:
   ```
   Garmin / NewFiles /
   ```
5. Safely eject the watch — workouts will appear under **Training**

> **Note:** some watch models may not appear as a drive automatically — use Garmin Express in that case (see below).

---

### Option B — Garmin Express (computer + USB)

[Garmin Express](https://www.garmin.com/en-US/software/express/) is the official app for syncing your watch with your computer.

1. Download and install Garmin Express from **garmin.com/express**
2. Connect your watch via USB
3. Add your device in Garmin Express
4. Open the **Workouts** tab and import the `.fit` files
5. Click **Sync**

---

### Option C — Garmin Calendar (no USB, via app)

The most convenient option — workouts upload directly to your Garmin Connect account.

**Requirements:** Garmin Connect account (free at connect.garmin.com)

**How it works:**
1. In the bot: `/connect_garmin` — log in to Garmin Connect (email + password)
   - Your password is only used by the upload library to obtain an auth token
   - The token is cached locally; your password is never stored
2. Build a plan: send text → `/build`
3. In the delivery dialog choose **📅 Upload to Garmin Calendar**
4. Open **Garmin Connect** on your phone → tap Sync
5. Workouts will appear on your watch under **Training** → **Scheduled**

> **Tip:** after the first login, re-authentication is not required — your token is saved.
