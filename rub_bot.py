
import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()
if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("RUBIKA_BOT_TOKEN را در .env تنظیم کن")

import db
from tg_userbot import parse_tme_link

# ──────────────────────────── import rubpy ───────────────────────────────────
try:
    from rubpy.bot import BotClient, filters as bot_filters
    _USE_BOTCLIENT = True
    print("✅ rubpy BotClient لود شد.")
except ImportError:
    _USE_BOTCLIENT = False
    print("⚠️  BotClient یافت نشد — از polling استفاده می‌شه.")

# ─────────────────────────── regex ───────────────────────────────────────────
CODE_RE       = re.compile(r"^[A-Z0-9]{8}$")
TME_URL_RE    = re.compile(r"https?://t\.me/\S+")
JOIN_URL_RE   = re.compile(r"https?://t\.me/\+\S+")
SEARCH_CMD_RE = re.compile(r"^/search\s+(@\S+)\s+(.+)$", re.IGNORECASE)
GETPOST_CMD_RE= re.compile(r"^/getpost\s+(@\S+)\s+(\d+)$", re.IGNORECASE)
LATEST_CMD_RE = re.compile(r"^/latest\s+(@\S+)(?:\s+(\d+))?$", re.IGNORECASE)


# ─────────────────────────── پردازش پیام ─────────────────────────────────────

def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    text = (text or "").strip()

    # ── /start
    if text.startswith("/start"):
        return (
            "سلام! 👋 به **ربات Tele2Rub** خوش اومدی!\n\n"
            "**روش استفاده:**\n\n"
            "1️⃣ **انتقال فایل:**\n"
            "   کد ۸ کاراکتری از ربات تلگرام رو اینجا بفرست\n"
            "   مثال: `AB12CD34`\n\n"
            "2️⃣ **لینک پست عمومی:**\n"
            "   `https://t.me/channel/123`\n\n"
            "3️⃣ **پست خصوصی — اول لینک جوین:**\n"
            "   `https://t.me/+xxxxx`\n"
            "   بعد لینک پست:\n"
            "   `https://t.me/c/1234567890/55`\n\n"
            "4️⃣ **جستجو در کانال:**\n"
            "   `/search @channel کلمه`\n\n"
            "5️⃣ **دریافت پست خاص:**\n"
            "   `/getpost @channel 1234`\n\n"
            "6️⃣ **آخرین پست‌ها:**\n"
            "   `/latest @channel` یا `/latest @channel 10`"
        )

    # ── /help
    if text.startswith("/help"):
        return (
            "📖 **راهنما:**\n\n"
            "`کد ۸ رقمی` — دریافت فایل از تلگرام\n"
            "`لینک t.me` — دریافت محتوای پست\n"
            "`لینک +xxx` — عضویت در کانال خصوصی\n"
            "`/search @ch کلمه` — جستجو\n"
            "`/getpost @ch 123` — دریافت پست\n"
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
            f"⏳ نتایج به زودی ارسال می‌شود..."
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
            f"⏳ در حال پردازش..."
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
            f"⏳ در حال پردازش..."
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
                f"⏳ در حال دریافت محتوا..."
            )
        elif parsed["type"] == "private":
            db.push_rubika_task(sender_id, "telegram_link", {
                "url":        url,
                "channel_id": parsed["channel_id"],
                "msg_id":     parsed["msg_id"],
                "chat_id":    chat_id,
                "private":    True,
            })
            return (
                f"🔒 پست خصوصی دریافت شد.\n\n"
                f"⏳ در حال دریافت..."
            )
        else:
            return "❓ لینک ناشناخته. از لینک‌های معتبر t.me استفاده کن."

    # ── کد ۸ کاراکتری
    code = text.upper()
    if CODE_RE.match(code):
        file_record = db.get_file_by_code(code)
        if not file_record:
            return (
                f"❌ کد `{code}` پیدا نشد.\n"
                f"مطمئن شو کد را درست وارد کردی."
            )
        if file_record["delivered"]:
            return (
                f"⚠️ این فایل قبلاً تحویل داده شده.\n"
                f"اگر دریافت نکردی با پشتیبانی تماس بگیر."
            )
        db.push_forward(code, sender_id)
        return (
            f"✅ درخواست دریافت شد!\n\n"
            f"🎫 کد: `{code}`\n"
            f"📄 فایل: `{file_record['file_name']}`\n"
            f"📦 حجم: `{db.pretty_size(file_record['file_size'])}`\n\n"
            f"⏳ فایل در حال آماده‌سازی است..."
        )

    # ── پیش‌فرض
    return (
        "❓ دستور ناشناخته.\n\n"
        "کد ۸ کاراکتری فایل یا لینک t.me بفرست.\n"
        "برای راهنما: `/help`"
    )


# ─────────────────────── اجرا با BotClient ───────────────────────────────────

def run_with_botclient():
    app = BotClient(RUBIKA_BOT_TOKEN)

    @app.on_update(bot_filters.private)
    async def on_message(client, update):
        try:
            text      = getattr(update, "text", "") or ""
            sender_id = getattr(update, "sender_id", "") or ""
            chat_id   = getattr(update, "chat_id", "") or ""
            if not sender_id or not chat_id:
                return
            reply = handle_message(sender_id, chat_id, text)
            await update.reply(reply)
        except Exception as e:
            print(f"[rub_bot] خطا: {e}")
            try:
                await update.reply("❌ خطای داخلی. دوباره امتحان کن.")
            except Exception:
                pass

    print("✅ ربات روبیکا در حال اجراست (BotClient)...")
    app.run()


# ─────────────────────── polling fallback ────────────────────────────────────

def _send_msg(chat_id: str, text: str):
    import requests
    try:
        url = f"https://messengerg2b1.iranlms.ir/v3/{RUBIKA_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"[rub_bot send] {e}")


def run_with_polling():
    import requests
    print("✅ ربات روبیکا در حال اجراست (polling)...")
    offset = None

    while True:
        try:
            url     = f"https://messengerg2b1.iranlms.ir/v3/{RUBIKA_BOT_TOKEN}/getUpdates"
            payload = {"limit": 10, "timeout": 30}
            if offset:
                payload["offset"] = offset
            resp    = requests.post(url, json=payload, timeout=35)
            data    = resp.json()
            updates = data.get("data", {}).get("updates", [])

            for upd in updates:
                offset    = upd.get("update_id", offset)
                msg       = upd.get("inline_message") or upd.get("message", {})
                text      = msg.get("text", "") or ""
                sender_id = msg.get("sender_id", "") or ""
                chat_id   = msg.get("chat_id", "") or ""
                if not chat_id:
                    continue
                reply = handle_message(sender_id, chat_id, text)
                _send_msg(chat_id, reply)

        except Exception as e:
            print(f"[rub_bot] {e}")
            time.sleep(3)


# ─────────────────────────── main ────────────────────────────────────────────

if __name__ == "__main__":
    if _USE_BOTCLIENT:
        run_with_botclient()
    else:
        run_with_polling()