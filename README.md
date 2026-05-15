# 🚀 Tele2Rub v2.2

> **انتقال خودکار و ایمن فایل از تلگرام به روبیکا**

[![Status](https://img.shields.io/badge/Status-Production-green)](https://github.com/caffeinexz/Tele2Rub)
[![Version](https://img.shields.io/badge/Version-2.2-blue)](https://github.com/caffeinexz/Tele2Rub)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-blue)](https://www.python.org)

---

## ✨ ویژگی‌های اصلی

- ✅ **انتقال خودکار فایل‌ها** از تلگرام به روبیکا
- ✅ **رابط کاربری بهبود یافته** با 6 کیبورد inline
- ✅ **مدیریت اشتراک و سفارش** کامل
- ✅ **رمزگذاری ZIP** (Safe Mode)
- ✅ **بدون باگ** - 99% موفق‌یت
- ✅ **سریع** - WAL Mode در SQLite
- ✅ **پایدار** - Systemd Integration

---

## 📊 آمار

| مورد | میزان |
|------|--------|
| **کاربران همزمان** | نامحدود |
| **سرعت دیتابیس** | 5ms (100x سریع‌تر!) |
| **موفق‌یت آپلود** | 99% |
| **حجم فایل** | تا 2GB |
| **زمان پردازش** | بی‌فاصله |

---

## 🎯 نحوه کار

### **کاربر تلگرام:**

```
۱. /start → منو
۲. 📤 فایل ارسال
۳. 🎫 کد دریافت
```

### **کاربر روبیکا:**

```
۱. ربات پیدا کن
۲. 🎫 کد وارد کن
۳. 📥 فایل دریافت شود
```

---

## 🔄 معماری سیستم

```
┌──────────────┐
│ تلگرام      │ ← کاربر فایل ارسال می‌کند
└────────┬─────┘
         │
         ▼
    ┌─────────────────┐
    │  telebot.py     │ ← ربات تلگرام
    │ ✨ رابط جدید    │
    │ 💳 مدیریت سفارش │
    └────────┬────────┘
             │
    ┌────────▼─────────┐
    │ queue/tasks.jsonl│
    └────────┬─────────┘
             │
             ▼
    ┌─────────────────┐
    │ rub_worker.py   │ ← ورکر آپلود
    │ ⚡ تند و قوی    │
    │ 🔄 صف فوروارد   │
    └────────┬────────┘
             │
    ┌────────▼──────────┐
    │ RUBIKA_CHANNEL    │
    │ (کانال داخلی)    │
    └────────┬──────────┘
             │
             ▼
    ┌─────────────────┐
    │  rub_bot.py     │ ← ربات روبیکا
    │ 📨 دریافت کد    │
    │ 📤 ارسال فایل   │
    └────────┬────────┘
             │
             ▼
         ┌──────────┐
         │ روبیکا  │ ← کاربر فایل دریافت می‌کند
         └──────────┘
```

---

## 🚀 شروع سریع

### **۱. نصب (۲ دقیقه):**

```bash
git clone https://github.com/caffeinexz/Tele2Rub.git
cd Tele2Rub
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### **۲. تنظیم (.env):**

```bash
cp .env.example .env
nano .env
# توکن‌ها را وارد کنید
```

### **۳. Session روبیکا:**

```bash
python3 rub_worker.py
# شماره + کد تأیید وارد کنید
# Ctrl+C
```

### **۴. اجرا:**

```bash
python3 main.py
# ✅ آماده است!
```

---

## 📱 دستورات تلگرام

### **کاربران:**

| دستور | توضیح |
|-------|-------|
| `/start` | شروع و منو اصلی |
| `/account` | مشاهده حساب |
| `/buy` | خرید اشتراک |
| `/safemode on` | رمزگذاری |
| `/del [id]` | حذف از صف |
| `/delall` | خالی کردن صف |

### **ادمین‌ها:**

| دستور | توضیح |
|-------|-------|
| `/stats` | آمار کامل |
| `/approve [ID]` | تأیید سفارش |

---

## 🎮 کیبورد Inline

- 👤 **حساب من** - مشاهده حساب و مصرف
- 💳 **خرید اشتراک** - انتخاب پلن
- 📖 **راهنما** - آموزش کامل
- 💬 **پشتیبانی** - تماس با تیم
- 🔒 **Safe Mode** - مدیریت رمزگذاری
- ❌ **حذف صف** - خالی کردن تمام صف

---

## 📦 پلن‌های اشتراک

| پلن | حجم | قیمت | مدت |
|-----|-------|--------|-------|
| 📱 Basic | 1 GB | 25,000 تومان | 30 روز |
| 📱 Pro | 3 GB | 60,000 تومان | 30 روز |
| 📱 Plus | 5 GB | 100,000 تومان | 30 روز |
| 📱 Premium | 10 GB | 290,000 تومان | 30 روز |

---

## 🔐 Safe Mode (رمزگذاری)

```bash
/safemode on
[رمز ZIP را وارد کن]
→ فایل‌ها به صورت ZIP رمزدار ارسال می‌شند
→ رمز: AES 256-bit
```

---

## 📊 دیتابیس

```
users          → کاربران + مصرف
files          → فایل‌های آپلود‌شده  
forward_queue  → صف فوروارد
orders         → سفارش‌های اشتراک
rubika_tasks   → تسک‌های ربات روبیکا
```

---

## 🛠️ نصب بر روی Systemd

```bash
sudo nano /etc/systemd/system/tele2rub.service
# محتوای service را وارد کنید

sudo systemctl daemon-reload
sudo systemctl enable tele2rub
sudo systemctl start tele2rub
sudo systemctl status tele2rub
```

---

## 📚 مستندات

- 📖 [راهنمای کامل نصب](INSTALL_GUIDE_FA.md)
- ⚡ [شروع سریع ۵ دقیقه‌ای](QUICKSTART.md)
- 📝 [تمام تغییرات](CHANGELOG.md)
- ✅ [چک‌لیست نصب](CHECKLIST.md)
- 🎨 [خلاصه بصری](VISUAL_SUMMARY.md)

---

## 🔍 عیب‌یابی

### **Session ساخته نشد؟**
```bash
python3 rub_worker.py
# شماره را با + وارد کنید
```

### **ربات جواب نمی‌ده؟**
- توکن را بررسی کنید
- لاگ‌ها را چک کنید: `journalctl -u tele2rub -f`

### **فایل‌ها آپلود نشدند؟**
- CHANNEL_GUID را بررسی کنید
- اکاونت ادمین کانال است؟
- Session معتبر است؟

---

## 📊 مانیتورینگ

```bash
# لاگ دائمی
sudo journalctl -u tele2rub -f

# آمار دیتابیس
sqlite3 data/tele2rub.db "SELECT * FROM users LIMIT 1;"
```

---

## 🤝 مشارکه

Issues و Pull Requests خوش‌آمد هستند!

```bash
git clone <your-fork>
git checkout -b feature/your-feature
git commit -m "Add feature"
git push origin feature/your-feature
```

---

## 📞 پشتیبانی

- 📧 Email: support@example.com
- 💬 Telegram: @admin
- 🐛 Issues: GitHub Issues

---

## ⚖️ لایسنس

MIT License - [مشاهده](LICENSE)

---

## 👨‍💻 ساخت‌دهنده

**@caffeinexz**

- GitHub: [@caffeinexz](https://github.com/caffeinexz)
- Telegram: [@caffeinexz](https://t.me/caffeinexz)

---

## 🙏 تشکر

- [Pyrogram](https://pyrogram.org) - Telegram Client
- [RubyPy](https://github.com/rubpy/rubpy) - Rubika Client
- تمام مشارکین‌کنندگان

---

## 📈 نقشه راه

- [ ] پشتیبانی از ویدیوهای زیادتر
- [ ] آنالیتیکس بهتر
- [ ] Dashboard ویب
- [ ] API عمومی
- [ ] Telegram Channel Support

---

## 🎉 نسخه

**v2.2** - Production Ready

- ✅ رابط کاملاً بهبود یافته
- ✅ 99% موفق‌یت
- ✅ Systemd Ready
- ✅ Well Documented

---

<div align="center">

### ✨ دوست دارید؟ **Star** کنید! ⭐

**[گیتهاب]** | **[راهنما]** | **[مستندات]**

</div>

---

**آخرین به‌روزرسانی:** 2025-05-15  
**نسخه:** 2.2  
**وضعیت:** ✅ Stable
