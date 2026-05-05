# 🚀 Tele2Rub — راهنمای کامل نصب و راه‌اندازی

انتقال خودکار فایل از تلگرام به روبیکا — با پروفایل کاربری، اشتراک، کد یونیک و ربات روبیکا

---

## 📐 معماری کلی پروژه

```
┌─────────────────────────────────────────────────────────┐
│                      کاربر تلگرام                        │
│  ارسال فایل → ربات تلگرام → دریافت کد یونیک            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│               telebot.py  (ربات تلگرام)                  │
│  - مدیریت پروفایل کاربران                               │
│  - بررسی اشتراک                                          │
│  - دانلود فایل از تلگرام                                 │
│  - ثبت در صف + دیتابیس                                   │
│  - ارسال کد یونیک به کاربر                               │
└──────────────────────┬──────────────────────────────────┘
                       │  queue/tasks.jsonl
                       ▼
┌─────────────────────────────────────────────────────────┐
│              rub_worker.py  (ورکر روبیکا)                │
│  - خواندن صف                                             │
│  - آپلود فایل در کانال خصوصی روبیکا                     │
│  - ذخیره message_id در دیتابیس                           │
│  - پردازش صف فوروارد                                     │
└──────────────────────┬──────────────────────────────────┘
                       │  data/tele2rub.db
                       ▼
┌─────────────────────────────────────────────────────────┐
│               rub_bot.py  (ربات روبیکا)                  │
│  - دریافت کد یونیک از کاربر روبیکا                      │
│  - جستجو در دیتابیس                                      │
│  - فوروارد فایل از کانال خصوصی به کاربر                 │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 ساختار فایل‌ها

```
tele2rub/
├── main.py            # اجراکننده اصلی (همه پروسه‌ها)
├── telebot.py         # ربات تلگرام
├── rub_worker.py      # ورکر آپلود روبیکا
├── rub_bot.py         # ربات روبیکا
├── db.py              # لایه دیتابیس SQLite
├── requirements.txt
├── .env.example
├── .env               # (خودت می‌سازی)
├── data/
│   └── tele2rub.db    # دیتابیس SQLite
├── downloads/         # فایل‌های دانلود‌شده موقت
├── archive/           # نسخه ذخیره‌شده فایل‌ها
└── queue/             # فایل‌های صف و وضعیت
    ├── tasks.jsonl
    ├── status.jsonl
    ├── settings.json
    ├── cancelled.jsonl
    ├── deleted.jsonl
    ├── failed.jsonl
    └── processing.json
```

---

## 🛠️ مرحله ۱ — پیش‌نیازها (سرور لینوکس)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip git screen -y
```

---

## 🛠️ مرحله ۲ — دریافت پروژه

```bash
git clone https://github.com/caffeinexz/Tele2Rub.git
cd Tele2Rub
```

یا اگر کد جدید داری:
```bash
mkdir tele2rub && cd tele2rub
# فایل‌ها رو کپی کن
```

---

## 🛠️ مرحله ۳ — محیط مجازی

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 🔑 مرحله ۴ — دریافت توکن‌ها و تنظیمات

### ۴.۱ — API تلگرام (API_ID و API_HASH)

1. به **https://my.telegram.org** برو
2. با شماره تلگرامت وارد شو
3. روی **API development tools** کلیک کن
4. فرم رو پر کن:
   ```
   App title: Tele2Rub
   Short name: t2r
   ```
5. `API_ID` و `API_HASH` رو کپی کن

### ۴.۲ — توکن ربات تلگرام (BOT_TOKEN)

1. در تلگرام، به **@BotFather** برو
2. بفرست `/newbot`
3. نام و یوزرنیم بده
4. توکن رو کپی کن

### ۴.۳ — ساخت ربات روبیکا (RUBIKA_BOT_TOKEN)

> ⚠️ **مهم:** ربات روبیکا با توکن کار می‌کنه، نه session.

**مراحل ساخت ربات در روبیکا:**

1. اپلیکیشن روبیکا رو باز کن
2. سرچ کن: **@BotFather** (یا به دنبال ربات رسمی ساخت ربات روبیکا بگرد)
3. دستور `/newbot` رو بفرست
4. نام ربات رو وارد کن (مثلاً: `Tele2Rub Bot`)
5. یوزرنیم ربات رو وارد کن (باید با `_bot` تموم بشه، مثلاً: `tele2rub_bot`)
6. توکن ۳۲ کاراکتری دریافت می‌کنی → این مقدار `RUBIKA_BOT_TOKEN` هست

> **نکته:** اگر @BotFather روبیکا پیدا نکردی:
> - در روبیکا سرچ کن: `ساخت ربات` یا `bot father`
> - یا از طریق وب‌سایت روبیکا اقدام کن

### ۴.۴ — کانال خصوصی روبیکا (RUBIKA_CHANNEL_GUID)

1. در روبیکا یه **کانال خصوصی** بساز (Private Channel)
2. ربات کاربری (account session) رو به کانال **ادمین** کن
3. GUID کانال رو پیدا کن:
   - از طریق کد پایتون:
     ```python
     from rubpy import Client
     with Client(name='rubika_session') as c:
         info = c.getChatsUpdates()
         print(info)
     ```
   - یا بعد از اجرای اول، از لاگ‌ها استخراج کن
   - GUID کانال با `c0` شروع می‌شه

### ۴.۵ — آیدی عددی ادمین تلگرام

1. در تلگرام به **@userinfobot** برو
2. `/start` بفرست
3. آیدی عددی‌ات رو کپی کن

---

## ⚙️ مرحله ۵ — ساخت فایل .env

```bash
cp .env.example .env
nano .env
```

مقادیر رو پر کن:

```env
# ─── تلگرام ──────────────────────────────────────────────────
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
BOT_TOKEN=1234567890:AABBCCyour_bot_token

# آیدی عددی ادمین‌ها (جدا با کاما)
ADMIN_IDS=123456789

# ─── روبیکا (کاربر) ──────────────────────────────────────────
RUBIKA_SESSION=rubika_session
RUBIKA_CHANNEL_GUID=c0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ─── روبیکا (ربات) ───────────────────────────────────────────
RUBIKA_BOT_TOKEN=your_rubika_bot_token_here
```

ذخیره: `Ctrl+X` → `Y` → `Enter`

---

## 🚀 مرحله ۶ — اجرای اولیه (ورود به روبیکا)

اول باید session کاربر روبیکا رو بسازیم:

```bash
source venv/bin/activate
python3 rub_worker.py
```

- شماره روبیکا رو وارد کن (با کد کشور، مثلاً: `+989123456789`)
- کد تأیید رو وارد کن
- فایل session ذخیره میشه (مثلاً: `rubika_session.session`)
- با `Ctrl+C` متوقف کن

---

## 🖥️ مرحله ۷ — اجرای دائمی با Screen

```bash
# یه screen جدید بساز
screen -S tele2rub

# محیط مجازی رو فعال کن
source venv/bin/activate

# پروژه رو اجرا کن
python3 main.py
```

برای خروج از screen (بدون توقف):
```
Ctrl+A  →  D
```

برای برگشت به screen:
```bash
screen -r tele2rub
```

---

## 🖥️ مرحله ۷ (جایگزین) — اجرا با systemd (حرفه‌ای‌تر)

### ساخت service file:

```bash
sudo nano /etc/systemd/system/tele2rub.service
```

محتوا:
```ini
[Unit]
Description=Tele2Rub Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/tele2rub
ExecStart=/home/ubuntu/tele2rub/venv/bin/python3 main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> ⚠️ مسیر `/home/ubuntu/tele2rub` رو با مسیر واقعی پروژه‌ات عوض کن

فعال‌سازی:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tele2rub
sudo systemctl start tele2rub
sudo systemctl status tele2rub
```

مشاهده لاگ:
```bash
journalctl -u tele2rub -f
```

---

## 📱 مرحله ۸ — نحوه استفاده

### کاربر تلگرام:

1. ربات تلگرام رو باز کن
2. `/start` بفرست
3. برای اولین بار، ادمین باید اشتراک بده (دستور `/addsub`)
4. فایل رو بفرست → فایل دانلود و آپلود میشه
5. یه کد ۸ کاراکتری دریافت می‌کنی مثل: `AB12CD34`

### کاربر روبیکا:

1. ربات روبیکا رو پیدا کن
2. کد ۸ کاراکتری که از تلگرام گرفتی رو بفرست
3. فایل برات ارسال میشه ✅

---

## 👑 دستورات ادمین (تلگرام)

| دستور | توضیح |
|-------|-------|
| `/addsub USER_ID DAYS` | اشتراک N روزه برای کاربر |
| `/delsub USER_ID` | حذف اشتراک کاربر |

مثال:
```
/addsub 123456789 30
/delsub 123456789
```

---

## 👤 دستورات کاربر (تلگرام)

| دستور | توضیح |
|-------|-------|
| `/start` | شروع و راهنما |
| `/profile` | مشاهده پروفایل و آمار مصرف |
| `/sub` | وضعیت اشتراک |
| `/safemode on` | فعال‌سازی رمزگذاری ZIP |
| `/safemode off` | غیرفعال‌سازی رمزگذاری |
| `/del JOB_ID` | حذف یک مورد از صف |
| `/delall` | پاکسازی کل صف |

---

## 🗄️ ساختار دیتابیس

### جدول `users`
| ستون | توضیح |
|------|-------|
| telegram_id | آیدی عددی تلگرام (کلید اصلی) |
| username | یوزرنیم تلگرام |
| first_name / last_name | نام و نام خانوادگی |
| joined_at | تاریخ عضویت |
| total_bytes | حجم کل مصرفی |
| sub_active | آیا اشتراک دارد |
| sub_expires | تاریخ انقضای اشتراک |

### جدول `files`
| ستون | توضیح |
|------|-------|
| unique_code | کد ۸ کاراکتری یونیک |
| telegram_user_id | صاحب فایل |
| file_name / file_size | اطلاعات فایل |
| archive_path | مسیر ذخیره محلی |
| rubika_channel_guid | GUID کانال روبیکا |
| rubika_message_id | شناسه پست در کانال |
| delivered | آیا تحویل داده شده |

### جدول `forward_queue`
| ستون | توضیح |
|------|-------|
| unique_code | کد درخواست‌شده |
| rubika_user_id | GUID کاربر روبیکا |
| status | pending / processing / done / failed |

---

## 🔧 عیب‌یابی

### مشکل: session روبیکا نمی‌سازه
```bash
# مطمئن شو شماره با کد کشور وارد می‌کنی
# مثال: +989123456789
python3 -c "from rubpy import Client; c = Client('rubika_session'); c.start(); c.disconnect()"
```

### مشکل: ربات روبیکا پاسخ نمیده
- مطمئن شو `RUBIKA_BOT_TOKEN` درسته
- بررسی کن ربات در روبیکا ساخته شده
- لاگ‌ها رو چک کن:
```bash
journalctl -u tele2rub -f | grep rub_bot
```

### مشکل: فایل‌ها در کانال آپلود نمیشن
- مطمئن شو `RUBIKA_CHANNEL_GUID` درسته (با `c0` شروع میشه)
- account روبیکا رو ادمین کانال کن
- session معتبر باشه

### مشکل: GUID کانال رو بلد نیستم پیدا کنم
```python
from rubpy import Client

with Client(name='rubika_session') as client:
    result = client.getChats()
    for chat in result:
        print(f"نام: {chat.get('title')} | GUID: {chat.get('object_guid')}")
```

### مشکل: `ModuleNotFoundError`
```bash
source venv/bin/activate
pip install -r requirements.txt
```

---

## 📊 نظارت و مشاهده لاگ

```bash
# همه لاگ‌ها
journalctl -u tele2rub -f

# بررسی فایل‌های failed
cat queue/failed.jsonl | python3 -m json.tool

# آمار دیتابیس
sqlite3 data/tele2rub.db "SELECT telegram_id, first_name, total_bytes, sub_active FROM users;"
sqlite3 data/tele2rub.db "SELECT unique_code, file_name, delivered FROM files ORDER BY id DESC LIMIT 20;"
```

---

## 🔄 آپدیت پروژه

```bash
screen -r tele2rub
# Ctrl+C برای توقف

git pull

source venv/bin/activate
pip install -r requirements.txt

python3 main.py
# Ctrl+A → D برای detach
```

---

## ❓ سؤالات متداول

**Q: آیا فایل‌ها روی سرور ذخیره می‌مونن؟**
A: بله، پوشه `archive/` فایل‌ها رو نگه می‌داره تا ربات روبیکا بتونه فوروارد کنه. برای صرفه‌جویی در فضا می‌تونی بعد از تحویل (`delivered=1`) پاکشون کنی.

**Q: حداکثر حجم فایل؟**
A: تا ۲ گیگابایت (محدودیت روبیکا).

**Q: چند کاربر همزمان؟**
A: صف یک‌به‌یک پردازش میشه، اما می‌تونی چند ورکر موازی اجرا کنی.

**Q: آیا کد یونیک منقضی میشه؟**
A: در حالت فعلی خیر. می‌تونی به راحتی منطق انقضا رو به `db.py` اضافه کنی.

---

@caffeinexz
