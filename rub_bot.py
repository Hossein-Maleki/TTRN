"""
rub_bot.py — ربات روبیکا (رفع‌شده)
دریافت کد یونیک از کاربر، جستجو در دیتابیس، فوروارد فایل

اصلاحات:
- استفاده صحیح از rubpy BotClient با دسترسی درست به attributeها
- polling قوی با endpoint‌های متعدد
- لاگ کامل برای دیباگ
- fallback چندلایه
"""

import os
import re
import time
import logging
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────── لاگ ────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [rub_bot] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rub_bot")

# ──────────────────────────── توکن ───────────────────────────────────────────

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()
if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("❌  RUBIKA_BOT_TOKEN را در .env تنظیم کن")

import db
from tg_userbot import parse_tme_link

# ──────────────────────────── regex ──────────────────────────────────────────

CODE_RE        = re.compile(r"^[A-Z0-9]{8}$")
TME_URL_RE     = re.compile(r"https?://t\.me/\S+")
JOIN_URL_RE    = re.compile(r"https?://t\.me/\+\S+")
SEARCH_CMD_RE  = re.compile(r"^/search\s+(@\S+)\s+(.+)$",      re.IGNORECASE)
GETPOST_CMD_RE = re.compile(r"^/getpost\s+(@\S+)\s+(\d+)$",    re.IGNORECASE)
LATEST_CMD_RE  = re.compile(r"^/latest\s+(@\S+)(?:\s+(\d+))?$", re.IGNORECASE)


# ─────────────────────────── پردازش پیام ─────────────────────────────────────

def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    """پردازش متن پیام و برگرداندن پاسخ مناسب"""
    text = (text or "").strip()
    log.info(f"پیام از {sender_id[:12]}… | chat={chat_id[:12]}… | متن=«{text[:40]}»")

    # ── /start
    if text.lower().startswith("/start"):
        return (
            "سلام! 👋 به **ربات Tele2Rub** خوش اومدی!\n\n"
            "**روش استفاده:**\n\n"
            "1️⃣ **انتقال فایل:**\n"
            "   کد ۸ کاراکتری از ربات تلگرام رو اینجا بفرست\n"
            "   مثال: `AB12CD34`\n\n"
            "2️⃣ **لینک پست عمومی تلگرام:**\n"
            "   `https://t.me/channel/123`\n\n"
            "3️⃣ **پست کانال خصوصی — ابتدا لینک جوین:**\n"
            "   `https://t.me/+xxxxx`\n"
            "   سپس لینک پست:\n"
            "   `https://t.me/c/1234567890/55`\n\n"
            "4️⃣ **جستجو در کانال:**\n"
            "   `/search @channel کلمه`\n\n"
            "5️⃣ **دریافت پست خاص:**\n"
            "   `/getpost @channel 1234`\n\n"
            "6️⃣ **آخرین پست‌ها:**\n"
            "   `/latest @channel` یا `/latest @channel 10`"
        )

    # ── /help
    if text.lower().startswith("/help"):
        return (
            "📖 **راهنمای دستورات:**\n\n"
            "`کد ۸ رقمی` — دریافت فایل از تلگرام\n"
            "`لینک t.me` — دریافت محتوای پست\n"
            "`لینک +xxx` — عضویت در کانال خصوصی\n"
            "`/search @ch کلمه` — جستجو\n"
            "`/getpost @ch 123` — دریافت پست خاص\n"
            "`/latest @ch` — آخرین پست‌ها\n"
        )

    # ── /search @channel keyword
    m = SEARCH_CMD_RE.match(text)
    if m:
        channel = m.group(1)
        query   = m.group(2).strip()
        db.push_rubika_task(sender_id, "search", {
            "channel": channel,
            "query":   query,
            "chat_id": chat_id,
        })
        return (
            f"🔍 جستجو در `{channel}` برای: **{query}**\n\n"
            "⏳ نتایج به زودی ارسال می‌شود..."
        )

    # ── /getpost @channel msgid
    m = GETPOST_CMD_RE.match(text)
    if m:
        channel = m.group(1)
        msg_id  = int(m.group(2))
        db.push_rubika_task(sender_id, "getpost", {
            "channel": channel,
            "msg_id":  msg_id,
            "chat_id": chat_id,
        })
        return (
            f"📥 دریافت پست `{msg_id}` از `{channel}`\n\n"
            "⏳ در حال پردازش..."
        )

    # ── /latest @channel [n]
    m = LATEST_CMD_RE.match(text)
    if m:
        channel = m.group(1)
        limit   = min(int(m.group(2) or 5), 20)
        db.push_rubika_task(sender_id, "latest", {
            "channel": channel,
            "limit":   limit,
            "chat_id": chat_id,
        })
        return (
            f"📬 دریافت {limit} پست آخر از `{channel}`\n\n"
            "⏳ در حال پردازش..."
        )

    # ── لینک جوین کانال خصوصی
    if JOIN_URL_RE.match(text):
        parsed = parse_tme_link(text)
        if parsed["type"] == "join":
            db.push_rubika_task(sender_id, "join_channel", {
                "hash":    parsed["hash"],
                "chat_id": chat_id,
            })
            return "🔗 در حال عضویت در کانال خصوصی...\n⏳ لحظه‌ای صبر کن."

    # ── لینک پست تلگرام
    url_m = TME_URL_RE.search(text)
    if url_m:
        url    = url_m.group(0)
        parsed = parse_tme_link(url)
        if parsed["type"] == "public":
            db.push_rubika_task(sender_id, "telegram_link", {
                "url":     url,
                "channel": parsed["channel"],
                "msg_id":  parsed["msg_id"],
                "chat_id": chat_id,
            })
            return (
                f"📨 لینک دریافت شد:\n`{url}`\n\n"
                "⏳ در حال دریافت محتوا..."
            )
        elif parsed["type"] == "private":
            db.push_rubika_task(sender_id, "telegram_link", {
                "url":        url,
                "channel_id": parsed["channel_id"],
                "msg_id":     parsed["msg_id"],
                "chat_id":    chat_id,
                "private":    True,
            })
            return "🔒 پست خصوصی دریافت شد.\n\n⏳ در حال دریافت..."
        else:
            return "❓ لینک ناشناخته. از لینک‌های معتبر t.me استفاده کن."

    # ── کد ۸ کاراکتری
    code = re.sub(r"\s+", "", text.upper())
    if CODE_RE.match(code):
        file_record = db.get_file_by_code(code)
        if not file_record:
            return (
                f"❌ کد `{code}` پیدا نشد.\n"
                "مطمئن شو کد را درست وارد کردی."
            )
        if file_record["delivered"]:
            return (
                "⚠️ این فایل قبلاً تحویل داده شده.\n"
                "اگر دریافت نکردی با پشتیبانی تماس بگیر."
            )
        db.push_forward(code, sender_id)
        return (
            f"✅ درخواست دریافت شد!\n\n"
            f"🎫 کد: `{code}`\n"
            f"📄 فایل: `{file_record['file_name']}`\n"
            f"📦 حجم: `{db.pretty_size(file_record['file_size'])}`\n\n"
            "⏳ فایل در حال آماده‌سازی است..."
        )

    # ── پیش‌فرض
    return (
        "❓ دستور ناشناخته.\n\n"
        "کد ۸ کاراکتری فایل یا لینک t.me بفرست.\n"
        "برای راهنما: `/help`"
    )


# ═══════════════════════════════════════════════════════════════════════════
# روش ۱ — rubpy BotClient (اصلی)
# ═══════════════════════════════════════════════════════════════════════════

def _extract_update_fields(update) -> tuple:
    """
    استخراج sender_id، chat_id، text از آبجکت update ربات‌های روبیکا.
    rubpy ممکن است ساختارهای مختلفی داشته باشد؛ اینجا همه را چک می‌کنیم.
    """
    def safe(obj, *keys, default=""):
        for key in keys:
            val = getattr(obj, key, None)
            if val:
                return str(val)
        return default

    # حالت ۱: مستقیم روی update
    text      = safe(update, "text", "message_text")
    sender_id = safe(update, "sender_id", "author_object_guid", "from_object_guid")
    chat_id   = safe(update, "chat_id", "object_guid")

    # حالت ۲: داخل inline_message
    if not chat_id:
        im = getattr(update, "inline_message", None) or getattr(update, "message", None)
        if im:
            text      = safe(im, "text", "message_text") or text
            sender_id = safe(im, "sender_id", "author_object_guid") or sender_id
            chat_id   = safe(im, "chat_id", "object_guid") or chat_id

    # حالت ۳: اگر آبجکت dict-like باشد
    if not chat_id and hasattr(update, "get"):
        im        = update.get("inline_message") or update.get("message") or update
        text      = im.get("text", "") if hasattr(im, "get") else text
        sender_id = im.get("sender_id", "") if hasattr(im, "get") else sender_id
        chat_id   = im.get("chat_id", "") if hasattr(im, "get") else chat_id

    return str(sender_id), str(chat_id), str(text)


def run_with_botclient():
    try:
        from rubpy.bot import BotClient, filters as bot_filters
    except ImportError as e:
        log.error(f"rubpy.bot import خطا: {e}")
        return False

    log.info("▶  شروع با rubpy BotClient...")
    app = BotClient(RUBIKA_BOT_TOKEN)

    @app.on_update()
    async def on_all(client, update):
        """تمام آپدیت‌ها را می‌گیریم تا چیزی از دست نرود"""
        try:
            sender_id, chat_id, text = _extract_update_fields(update)

            # لاگ دیباگ برای اطمینان از دریافت
            log.info(f"📩 update | sender={sender_id[:12]}… chat={chat_id[:12]}… text=«{text[:30]}»")

            if not chat_id:
                log.warning("chat_id خالی بود — skip")
                return

            reply_text = handle_message(sender_id, chat_id, text)

            # ارسال پاسخ
            try:
                await update.reply(reply_text)
            except Exception:
                # اگر reply کار نکرد، از client مستقیم استفاده کن
                try:
                    await client.send_message(chat_id, reply_text)
                except Exception as e2:
                    log.error(f"send_message خطا: {e2}")

        except Exception as e:
            log.error(f"on_update خطا: {e}", exc_info=True)
            try:
                await update.reply("❌ خطای داخلی. دوباره امتحان کن.")
            except Exception:
                pass

    log.info("✅ ربات روبیکا با BotClient در حال اجراست...")
    try:
        app.run()
        return True
    except Exception as e:
        log.error(f"BotClient.run() خطا: {e}", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# روش ۲ — Polling دستی (fallback قوی)
# ═══════════════════════════════════════════════════════════════════════════

# لیست endpoint‌های ممکن API روبیکا
_API_BASES = [
    "https://messengerg2b1.iranlms.ir/v3",
    "https://messengerg2c1.iranlms.ir/v3",
    "https://messengerg2d1.iranlms.ir/v3",
    "https://messengerg2b2.iranlms.ir/v3",
]


def _api_call(method: str, payload: dict, timeout: int = 35) -> dict:
    """فراخوانی API روبیکا با تلاش روی چند endpoint"""
    import requests

    for base in _API_BASES:
        url = f"{base}/{RUBIKA_BOT_TOKEN}/{method}"
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            data = resp.json()
            status = data.get("status") or data.get("status_det", "")
            if resp.status_code == 200 and status in ("OK", "ok", ""):
                return data
        except requests.exceptions.RequestException as e:
            log.debug(f"endpoint {base} خطا: {e}")
            continue
    return None


def _send_msg_polling(chat_id: str, text: str):
    result = _api_call("sendMessage", {"chat_id": chat_id, "text": text})
    if not result:
        log.error(f"ارسال پیام به {chat_id} ناموفق")


def run_with_polling():
    import requests

    log.info("▶  شروع با polling دستی...")

    # تست اتصال اولیه
    me = _api_call("getMe", {}, timeout=10)
    if me:
        log.info(f"✅ ربات متصل شد: {me}")
    else:
        log.warning("⚠️  getMe ناموفق — ادامه می‌دهیم...")

    offset = None

    while True:
        try:
            payload = {"limit": 20, "timeout": 30}
            if offset is not None:
                payload["offset"] = offset + 1

            result = _api_call("getUpdates", payload, timeout=35)

            if not result:
                log.warning("getUpdates پاسخ ندادند، ۵ ثانیه صبر...")
                time.sleep(5)
                continue

            # پیدا کردن لیست آپدیت‌ها در ساختار پاسخ
            updates = (
                result.get("data", {}).get("updates") or
                result.get("updates") or
                result.get("data") or
                []
            )
            if isinstance(updates, dict):
                updates = [updates]

            for upd in updates:
                # استخراج update_id
                uid = upd.get("update_id") or upd.get("inline_message", {}).get("message_id")
                if uid:
                    try:
                        offset = int(uid)
                    except (ValueError, TypeError):
                        pass

                # استخراج پیام
                msg = (
                    upd.get("inline_message") or
                    upd.get("message") or
                    upd
                )
                text      = msg.get("text", "") or ""
                sender_id = (
                    msg.get("sender_id") or
                    msg.get("author_object_guid") or ""
                )
                chat_id   = (
                    msg.get("chat_id") or
                    msg.get("object_guid") or ""
                )

                if not chat_id:
                    log.debug(f"آپدیت بدون chat_id: {upd}")
                    continue

                log.info(f"📩 پیام | sender={sender_id[:12]}… | «{text[:30]}»")
                reply_text = handle_message(sender_id, chat_id, text)
                _send_msg_polling(chat_id, reply_text)

        except KeyboardInterrupt:
            log.info("🛑 polling متوقف شد")
            break
        except Exception as e:
            log.error(f"polling خطا: {e}", exc_info=True)
            time.sleep(3)


# ══════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info(f"🤖 شروع ربات روبیکا | توکن: {RUBIKA_BOT_TOKEN[:10]}…")

    # اول BotClient را امتحان کن
    try:
        success = run_with_botclient()
        if not success:
            raise RuntimeError("BotClient ناموفق")
    except Exception as e:
        log.warning(f"BotClient کار نکرد ({e}). استفاده از polling...")
        run_with_polling()