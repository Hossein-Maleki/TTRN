# ✅ چک‌لیست کامل نصب Tele2Rub v2.2

## 🔧 مرحله پیش‌نیازها

- [ ] سیستم عامل: Ubuntu 20.04+ یا Debian
- [ ] Python 3.8+
- [ ] اتصال اینترنت
- [ ] حساب Telegram
- [ ] حساب Rubika
- [ ] دسترسی Sudo (برای Systemd)

---

## 📦 مرحله دانلود و نصب

- [ ] پروژه دانلود شد
  ```bash
  git clone https://github.com/caffeinexz/Tele2Rub.git
  ```

- [ ] وارد پوشه شدم
  ```bash
  cd Tele2Rub
  ```

- [ ] محیط مجازی ساخته شد
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

- [ ] کتابخانه‌ها نصب شدند
  ```bash
  pip install -r requirements.txt
  ```

---

## 🔐 مرحله توکن‌ها

### **Telegram API**
- [ ] به https://my.telegram.org رفتم
- [ ] API credentials دریافت کردم
- [ ] `API_ID` نوت شد
- [ ] `API_HASH` نوت شد

### **Telegram Bot Token**
- [ ] @BotFather پیدا شد
- [ ] `/newbot` ارسال شد
- [ ] نام ربات تعیین شد
- [ ] نام کاربری ربات تعیین شد (با `_bot`)
- [ ] `BOT_TOKEN` نوت شد

### **Rubika Bot Token**
- [ ] روبیکا اپلیکیشن باز شد
- [ ] @BotFather در روبیکا پیدا شد
- [ ] `/newbot` ارسال شد
- [ ] نام و نام کاربری تعیین شد
- [ ] `RUBIKA_BOT_TOKEN` نوت شد

### **Rubika Channel**
- [ ] کانال خصوصی ساخته شد
- [ ] اکاونت روبیکا ادمین کانال است
- [ ] `RUBIKA_CHANNEL_GUID` استخراج شد (c0xxxxx...)

### **Admin ID**
- [ ] @userinfobot پیدا شد
- [ ] آیدی عددی شخصی دریافت شد
- [ ] `ADMIN_IDS` نوت شد

---

## ⚙️ مرحله تنظیمات

- [ ] فایل `.env` ساخته شد
  ```bash
  cp .env.example .env
  nano .env
  ```

- [ ] مقادیر صحیح وارد شدند:
  - [ ] `API_ID` ✓
  - [ ] `API_HASH` ✓
  - [ ] `BOT_TOKEN` ✓
  - [ ] `ADMIN_IDS` ✓
  - [ ] `RUBIKA_SESSION` ✓
  - [ ] `RUBIKA_CHANNEL_GUID` ✓
  - [ ] `RUBIKA_BOT_TOKEN` ✓

- [ ] فایل `.env` ذخیره شد

---

## 🔑 مرحله Session Rubika

- [ ] اجرای ابتدایی:
  ```bash
  source venv/bin/activate
  python3 rub_worker.py
  ```

- [ ] شماره Rubika وارد شد (با کد کشور)
  ```
  +989123456789
  ```

- [ ] کد تأیید وارد شد
- [ ] `Ctrl+C` فشار داده شد
- [ ] فایل `rubika_session.session` ساخته شد

---

## 🚀 مرحله اجرا

### **روش اول: Screen**
- [ ] Screen شروع شد
  ```bash
  screen -S tele2rub
  ```

- [ ] محیط مجازی فعال شد
  ```bash
  source venv/bin/activate
  ```

- [ ] برنامه شروع شد
  ```bash
  python3 main.py
  ```

- [ ] `Ctrl+A` بعد `D` فشار داده شد

### **روش دوم: Systemd** (توصیه شده)
- [ ] Service file ساخته شد
  ```bash
  sudo nano /etc/systemd/system/tele2rub.service
  ```

- [ ] محتوای صحیح وارد شد ✓

- [ ] مسیرها درست تنظیم شدند ✓

- [ ] Service فعال شد
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable tele2rub
  sudo systemctl start tele2rub
  ```

- [ ] وضعیت چک شد
  ```bash
  sudo systemctl status tele2rub
  ```

---

## ✅ مرحله تست

### **ربات Telegram**
- [ ] ربات پیدا شد
- [ ] `/start` ارسال شد
- [ ] منوی اصلی نمایش داده شد
- [ ] کیبورد inline کار می‌کند
- [ ] یک فایل تست ارسال شد
- [ ] کد یونیک دریافت شد
- [ ] کد در صف قرار گرفت

### **ربات Rubika**
- [ ] ربات پیدا شد
- [ ] کد یونیک وارد شد
- [ ] فایل دریافت شد ✅

### **دیتابیس**
- [ ] دیتابیس موجود است
  ```bash
  ls -la data/tele2rub.db
  ```

- [ ] جدول‌ها ساخته شدند
  ```bash
  sqlite3 data/tele2rub.db ".tables"
  ```

- [ ] کاربر ثبت شد
  ```bash
  sqlite3 data/tele2rub.db "SELECT COUNT(*) FROM users;"
  ```

---

## 📊 مرحله مانیتورینگ

- [ ] لاگ‌ها مشاهده شدند
  ```bash
  sudo journalctl -u tele2rub -f
  ```

- [ ] خطایی وجود ندارد
- [ ] پیام‌های موفق نمایش داده می‌شود

---

## 🎮 مرحله کاربران

- [ ] **کاربر ۱ (معمولی):**
  - [ ] `/start` کرد
  - [ ] فایل ارسال کرد
  - [ ] کد دریافت کرد
  - [ ] در روبیکا کد وارد کرد
  - [ ] فایل دریافت کرد

- [ ] **کاربر ۲ (اشتراک):**
  - [ ] `/buy` کرد
  - [ ] پلن انتخاب کرد
  - [ ] رسید ارسال کرد
  - [ ] ادمین تأیید کرد
  - [ ] اشتراک فعال شد

- [ ] **ادمین:**
  - [ ] `/stats` کرد
  - [ ] آمار صحیح است
  - [ ] `/approve ORDER_ID` کرد
  - [ ] کاربر اطلاع رسید

---

## 🔒 مرحله امنیت

- [ ] `.env` در `.gitignore` است
  ```bash
  echo ".env" >> .gitignore
  ```

- [ ] توکن‌ها محفوظ هستند
- [ ] ADMIN_IDS صحیح است
- [ ] کانال خصوصی است
- [ ] دسترسی کاربران محدود است

---

## 📚 مرحله Documentation

- [ ] SUMMARY.md خوانده شد
- [ ] QUICKSTART.md خوانده شد
- [ ] INSTALL_GUIDE_FA.md خوانده شد
- [ ] CHANGELOG.md خوانده شد

---

## 🔧 مرحله Troubleshooting

### **اگر Session ساخته نشد:**
- [ ] شماره با `+` وارد شد
- [ ] کد تأیید درست وارد شد
- [ ] شبکه خوب است

### **اگر ربات Telegram جواب نداد:**
- [ ] توکن صحیح است
- [ ] API_ID و API_HASH صحیح هستند
- [ ] اینترنت خوب است

### **اگر فایل‌ها آپلود نشد:**
- [ ] RUBIKA_CHANNEL_GUID صحیح است
- [ ] اکاونت روبیکا ادمین است
- [ ] Session معتبر است

### **اگر Database خطا داد:**
- [ ] فایل database حذف شد
  ```bash
  rm data/tele2rub.db
  ```
- [ ] برنامه دوباره شروع شد
- [ ] database نو ساخته شد

---

## 📝 مرحله Backup

- [ ] دیتابیس backup شد
  ```bash
  cp data/tele2rub.db data/tele2rub.db.backup
  ```

- [ ] فایل‌های مهم backup شدند
- [ ] script backup نوشته شد (optional)

---

## 🎉 نتیجه نهایی

- [ ] **تمام موارد بالا انجام شدند!**
- [ ] **سیستم آماده به کار است! ✅**
- [ ] **بدون خطا و مشکل 🚀**

---

## 🆘 اگر مشکلی پیدا شد:

1. **لاگ‌ها را چک کنید:**
   ```bash
   sudo journalctl -u tele2rub -f
   ```

2. **مناسب کنید و دوباره شروع کنید:**
   ```bash
   sudo systemctl restart tele2rub
   ```

3. **اگر هنوز خطا است:**
   - دیتابیس را ریست کنید
   - Session را دوباره بسازید
   - `.env` را بررسی کنید

4. **آخری راه حل:**
   - GitHub Issues
   - Support Team

---

## 📞 مراجع سریع

| مورد | دستور |
|------|--------|
| شروع | `python3 main.py` |
| متوقف | `Ctrl+C` |
| لاگ | `journalctl -u tele2rub -f` |
| وضعیت | `systemctl status tele2rub` |
| ریست | `systemctl restart tele2rub` |
| دیتابیس | `sqlite3 data/tele2rub.db` |

---

## 🎓 اطلاعات مفید

- **نسخه:** 2.2
- **تاریخ:** 2025-05-15
- **وضعیت:** ✅ Stable
- **آخرین بهروزرسانی:** 2025-05-15

---

**✨ تبریک! سیستم شما کامل است! ✨**

برای مشاوره بیشتر:
- Documentation
- FAQ
- Support Team
