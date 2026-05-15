# 🚀 راهنمای نصب و راه‌اندازی Tele2Rub v2.2

## ✅ بهبودی‌های انجام شده:

- ✅ سیستم کیبورد inline **کامل و منسجم**
- ✅ مدیریت اشتراک **پیشرفته**
- ✅ آپلود فایل **بدون باگ**
- ✅ صف پردازش **قوی**
- ✅ فوروارد فایل **درست**

---

## 📋 مراحل نصب

### ۱. پیش‌نیازها (سرور لینوکس)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip git screen -y
```

### ۲. دریافت پروژه

```bash
git clone https://github.com/caffeinexz/Tele2Rub.git
cd Tele2Rub
```

### ۳. محیط مجازی

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### ۴. تنظیم فایل‌های جدید

**فایل‌های آپدیت شده را جایگزین کنید:**

```bash
# فایل‌های جدید شما:
cp telebot_updated.py telebot.py
cp rub_bot_updated.py rub_bot.py
cp rub_worker_updated.py rub_worker.py
# db.py را نیز بهروزرسانی کنید
```

### ۵. توکن‌ها و تنظیمات

**ساخت یا ویرایش `.env`:**

```bash
cp .env.example .env
nano .env
```

**مقادیر مورد نیاز:**

```env
# ─── تلگرام ────────────────────────────────────────────
API_ID=YOUR_API_ID
API_HASH=YOUR_API_HASH
BOT_TOKEN=YOUR_BOT_TOKEN
ADMIN_IDS=123456789,987654321

# ─── روبیکا (کاربر) ────────────────────────────────────
RUBIKA_SESSION=rubika_session
RUBIKA_CHANNEL_GUID=c0xxxxxxxxxxxxx

# ─── روبیکا (ربات) ────────────────────────────────────
RUBIKA_BOT_TOKEN=YOUR_RUBIKA_BOT_TOKEN
```

### ۶. ساخت Session روبیکا

**اجرای اول برای ورود:**

```bash
source venv/bin/activate
python3 rub_worker.py
```

**مراحل:**
1. شماره روبیکا رو با کد کشور وارد کن: `+989123456789`
2. کد تأیید رو وارد کن
3. فایل session ذخیره میشه
4. `Ctrl+C` را فشار بده

### ۷. اجرای دائمی

#### **گزینه الف: استفاده از Screen**

```bash
screen -S tele2rub
source venv/bin/activate
python3 main.py

# Ctrl+A بعد D برای خروج بدون توقف
```

برای برگشت:
```bash
screen -r tele2rub
```

#### **گزینه ب: استفاده از Systemd** (توصیه شده)

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
WorkingDirectory=/home/ubuntu/Tele2Rub
ExecStart=/home/ubuntu/Tele2Rub/venv/bin/python3 main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

فعال‌سازی:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tele2rub
sudo systemctl start tele2rub
sudo systemctl status tele2rub
```

مشاهده لاگ:
```bash
sudo journalctl -u tele2rub -f
```

---

## 🎮 نحوه استفاده

### **کاربر تلگرام:**

1. **ربات تلگرام** رو باز کن
2. **/start** بفرست
3. **فایل رو ارسال کن** → کد ۸ کاراکتری دریافت کن
4. مثال: `AB12CD34`

### **کاربر روبیکا:**

1. **ربات روبیکا** رو پیدا کن
2. **کد** رو وارد کن
3. **فایل** برایت ارسال میشه ✅

---

## 📱 دستورات تلگرام

### کاربران عام:
| دستور | توضیح |
|-------|-------|
| `/start` | شروع و منو اصلی |
| `/account` | مشاهده حساب و مصرف |
| `/sub` | وضعیت اشتراک |
| `/buy` | خرید اشتراک |
| `/safemode on` | فعال‌سازی رمزگذاری |
| `/safemode off` | غیرفعال‌سازی |
| `/del [id]` | حذف فایل از صف |
| `/delall` | خالی کردن صف |

### ادمین‌ها:
| دستور | توضیح |
|-------|-------|
| `/stats` | آمار کامل |
| `/approve [ORDER_ID]` | تأیید سفارش |
| `/reject [ORDER_ID] دلیل` | رد سفارش |

---

## 🎨 کیبورد Inline

### منو اصلی:
- 👤 **حساب من** → نمایش حساب و مصرف
- 💳 **خرید اشتراک** → پلن‌های مختلف
- 📖 **راهنما** → دستورات و راهنما
- 💬 **پشتیبانی** → اطلاعات تماس
- 🔒 **Safe Mode** → مدیریت رمزگذاری
- ❌ **حذف صف** → خالی کردن تمام صف

### صفحه حساب:
- 💳 خرید اشتراک
- 🔙 بازگشت

### صفحه خرید:
- دکمه برای هر پلن
- 🔙 بازگشت

---

## 🔧 عیب‌یابی

### مشکل: Session ساخته نمی‌شود
```bash
# مطمئن شو شماره با + وارد می‌کنی
python3 -c "from rubpy import Client; c = Client('test'); c.start()"
```

### مشکل: ربات روبیکا جواب نمی‌ده
- توکن را بررسی کن
- API endpoints در `rub_bot.py` را تست کن
- لاگ‌ها را مشاهده کن

### مشکل: فایل‌ها آپلود نمی‌شوند
- مطمئن شو `RUBIKA_CHANNEL_GUID` صحیح است
- کاربر روبیکا ادمین کانال است
- Session معتبر است

### خطای Database
```bash
rm data/tele2rub.db
# دیتابیس از نو ساخته خواهد شد
```

---

## 📊 مانیتورینگ

```bash
# لاگ دائمی
sudo journalctl -u tele2rub -f

# تعداد کاربران
sqlite3 data/tele2rub.db "SELECT COUNT(*) as users FROM users;"

# آمار فایل‌ها
sqlite3 data/tele2rub.db "SELECT COUNT(*) as files, COUNT(CASE WHEN delivered=1 THEN 1 END) as delivered FROM files;"

# درآمد
sqlite3 data/tele2rub.db "SELECT status, COUNT(*), SUM(amount) FROM orders GROUP BY status;"
```

---

## 🔄 به‌روزرسانی

```bash
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart tele2rub
```

---

## ⚙️ نکات مهم

### امنیت:
- ✅ `.env` در Git نباشد
- ✅ توکن‌ها محفوظ باشند
- ✅ ADMIN_IDS درست تنظیم شود

### کارایی:
- ✅ یک ورکر برای انتقال
- ✅ صف خودکار
- ✅ مدیریت خودکار خطاها

### پشتیبانی:
- 📧 Email: support@example.com
- 💬 Telegram: @admin

---

## 📞 پشتیبانی

اگر مشکل داشتی:
1. **لاگ‌ها** را چک کن
2. مشکل را در **Issues** ثبت کن
3. با **پشتیبان** تماس بگیر

---

**نسخه:** 2.2  
**آخرین به‌روزرسانی:** 2025-05-15  
**سازنده:** @caffeinexz
