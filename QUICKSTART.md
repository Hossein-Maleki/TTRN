# ⚡ Quick Start - شروع سریع (۵ دقیقه)

## 🚀 در ۵ مرحله

### مرحله ۱: نصب بسیار سریع
```bash
git clone https://github.com/caffeinexz/Tele2Rub.git
cd Tele2Rub
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### مرحله ۲: دریافت توکن‌ها

**تلگرام API:**
1. برو: https://my.telegram.org
2. API credentials دریافت کن
3. مقادیر رو نوت کن

**ربات تلگرام:**
1. @BotFather رو پیدا کن
2. /newbot بفرست
3. توکن رو نوت کن

**ربات روبیکا:**
1. روبیکا رو باز کن
2. @BotFather رو پیدا کن
3. /newbot بفرست
4. توکن رو نوت کن

### مرحله ۳: تنظیم سریع

```bash
cat > .env << EOF
API_ID=YOUR_API_ID
API_HASH=YOUR_API_HASH
BOT_TOKEN=YOUR_BOT_TOKEN
ADMIN_IDS=YOUR_USER_ID
RUBIKA_SESSION=rubika_session
RUBIKA_CHANNEL_GUID=YOUR_CHANNEL_ID
RUBIKA_BOT_TOKEN=YOUR_RUBIKA_BOT_TOKEN
EOF
```

### مرحله ۴: ساخت Session

```bash
python3 rub_worker.py
# شماره + کد تأیید وارد کن
# Ctrl+C
```

### مرحله ۵: اجرا

```bash
python3 main.py
# ✅ آماده است!
```

---

## 📱 اولین تست

### از طرف تلگرام:
```
/start
[انتخاب 👤 حساب من]
[فایلی را ارسال کن]
✅ کد دریافت کن
```

### از طرف روبیکا:
```
[کد را در ربات وارد کن]
✅ فایل دریافت شود
```

---

## 🎛️ مدیریت

**اجرا:**
```bash
python3 main.py
```

**توقف:**
```bash
Ctrl+C
```

**Systemd:**
```bash
sudo systemctl start tele2rub
sudo systemctl status tele2rub
sudo journalctl -u tele2rub -f
```

---

## ⚠️ عیب‌یابی سریع

| مشکل | حل |
|------|-----|
| Session ایجاد نشده | `python3 rub_worker.py` + شماره |
| ربات تلگرام پاسخ نمی‌ده | توکن درست را چک کن |
| فایل آپلود نشده | CHANNEL_GUID را بررسی کن |
| دیتابیس خطا | `rm data/tele2rub.db` و دوباره شروع |

---

## 📞 کمک!

**مشکل دارید؟**
1. لاگ‌ها را چک کنید
2. INSTALL_GUIDE_FA.md را بخوانید
3. Issue را ثبت کنید

---

**برای اطلاعات کامل:** INSTALL_GUIDE_FA.md  
**برای تغییرات:** CHANGELOG.md
