"""
tg_userbot.py — یوزربات تلگرام برای دسترسی به کانال‌ها
فچ پست، جستجو، آخرین پست‌ها
"""

import os
import re
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import (
    FloodWait, ChannelPrivate, UsernameInvalid,
    InviteHashExpired, InviteHashInvalid, UserAlreadyParticipant,
)

import db

load_dotenv()

API_ID   = int(os.getenv("API_ID",  "0"))
API_HASH = os.getenv("API_HASH", "").strip()
TG_USERBOT_SESSION = os.getenv("TG_USERBOT_SESSION", "tg_userbot").strip()

BASE_DIR     = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads" / "tg_fetch"
ARCHIVE_DIR  = BASE_DIR / "archive"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# لینک تلگرام
_PUBLIC_RE  = re.compile(r"t\.me/([a-zA-Z0-9_]+)/(\d+)")
_PRIVATE_RE = re.compile(r"t\.me/c/(\d+)/(\d+)")
_JOIN_RE    = re.compile(r"t\.me/\+([a-zA-Z0-9_\-]+)")


def parse_tme_link(url: str) -> dict:
    """
    Returns:
      {"type": "public",  "channel": "@chan",     "msg_id": 123}
      {"type": "private", "channel_id": 123456,   "msg_id": 55}
      {"type": "join",    "hash": "xxxxx"}
      {"type": "unknown"}
    """
    url = url.strip()
    m = _JOIN_RE.search(url)
    if m:
        return {"type": "join", "hash": m.group(1)}
    m = _PRIVATE_RE.search(url)
    if m:
        return {"type": "private", "channel_id": int(m.group(1)), "msg_id": int(m.group(2))}
    m = _PUBLIC_RE.search(url)
    if m:
        return {"type": "public", "channel": "@" + m.group(1), "msg_id": int(m.group(2))}
    return {"type": "unknown"}


def media_type_fa(message: Message) -> str:
    if message.document:  return "📄 فایل"
    if message.video:     return "🎬 ویدیو"
    if message.audio:     return "🎵 موزیک"
    if message.voice:     return "🎤 ویس"
    if message.photo:     return "🖼 عکس"
    if message.animation: return "🎭 گیف"
    if message.video_note:return "📹 ویدیو نوت"
    if message.sticker:   return "🎀 استیکر"
    return "📝 متن"


def message_info_text(msg: Message) -> str:
    mtype = media_type_fa(msg)
    size  = 0
    if msg.document:    size = msg.document.file_size or 0
    elif msg.video:     size = msg.video.file_size or 0
    elif msg.audio:     size = msg.audio.file_size or 0
    elif msg.voice:     size = msg.voice.file_size or 0
    elif msg.animation: size = msg.animation.file_size or 0

    views = msg.views or 0
    date  = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "—"
    cap   = (msg.caption or msg.text or "")[:200]

    text = (
        f"📌 **نوع:** {mtype}\n"
        f"📅 **زمان:** {date}\n"
        f"👁 **بازدید:** {views:,}\n"
    )
    if size:
        text += f"📦 **حجم:** {db.pretty_size(size)}\n"
    if cap:
        text += f"📝 **متن:**\n{cap}\n"
    return text


class TelegramUserbot:
    def __init__(self):
        self._app: Optional[Client] = None

    def _get_app(self) -> Client:
        if self._app is None:
            self._app = Client(
                name=TG_USERBOT_SESSION,
                api_id=API_ID,
                api_hash=API_HASH,
            )
        return self._app

    async def start(self):
        app = self._get_app()
        await app.start()

    async def stop(self):
        if self._app:
            try:
                await self._app.stop()
            except Exception:
                pass

    async def join_channel(self, invite_hash: str) -> str:
        """عضویت در کانال با هش دعوت. برمی‌گرداند: نام کانال"""
        app = self._get_app()
        try:
            chat = await app.join_chat(invite_hash)
            db.save_channel_access(str(chat.id))
            db.save_channel_access(chat.username or str(chat.id))
            return chat.title or str(chat.id)
        except UserAlreadyParticipant:
            return "قبلاً عضو بودید"
        except (InviteHashExpired, InviteHashInvalid):
            raise RuntimeError("لینک دعوت منقضی یا نامعتبر است.")

    async def fetch_message(self, channel: str, msg_id: int) -> Tuple[Message, str]:
        """
        دریافت یک پیام از کانال.
        channel: @username یا int
        Returns: (message, info_text)
        """
        app = self._get_app()
        try:
            msg = await app.get_messages(channel, msg_id)
            if not msg or msg.empty:
                raise RuntimeError("پیام پیدا نشد یا حذف شده.")
            return msg, message_info_text(msg)
        except (ChannelPrivate, UsernameInvalid):
            raise RuntimeError("دسترسی به کانال ندارید یا کانال پیدا نشد.")
        except FloodWait as e:
            await asyncio.sleep(e.value)
            msg = await app.get_messages(channel, msg_id)
            return msg, message_info_text(msg)

    async def download_message_media(self, msg: Message, prefix: str = "") -> Optional[Path]:
        """دانلود مدیای پیام و برگرداندن مسیر فایل"""
        app = self._get_app()
        has_media = any([
            msg.document, msg.video, msg.audio, msg.voice,
            msg.photo, msg.animation, msg.video_note, msg.sticker,
        ])
        if not has_media:
            return None

        out_path = DOWNLOAD_DIR / f"{prefix}_{msg.id}"
        try:
            downloaded = await app.download_media(msg, file_name=str(out_path))
            if downloaded:
                return Path(downloaded)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            downloaded = await app.download_media(msg, file_name=str(out_path))
            if downloaded:
                return Path(downloaded)
        return None

    async def search_channel(self, channel: str, query: str, limit: int = 10) -> List[Message]:
        """جستجو در کانال"""
        app = self._get_app()
        results = []
        try:
            async for msg in app.search_messages(channel, query=query, limit=limit):
                results.append(msg)
        except (ChannelPrivate, UsernameInvalid):
            raise RuntimeError("دسترسی به کانال ندارید یا کانال پیدا نشد.")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        return results

    async def get_latest(self, channel: str, limit: int = 5) -> List[Message]:
        """آخرین پیام‌های کانال"""
        app = self._get_app()
        results = []
        try:
            async for msg in app.get_chat_history(channel, limit=limit):
                results.append(msg)
        except (ChannelPrivate, UsernameInvalid):
            raise RuntimeError("دسترسی به کانال ندارید.")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        return results


_userbot = TelegramUserbot()


def get_userbot() -> TelegramUserbot:
    return _userbot


async def has_session() -> bool:
    for suffix in ["", ".session", ".sqlite"]:
        if Path(f"{TG_USERBOT_SESSION}{suffix}").exists():
            return True
    return False


async def ensure_userbot():
    if not await has_session():
        print("⚠️  session یوزربات تلگرام وجود ندارد — برخی امکانات غیرفعال است.")
        print(f"     اجرا کن: python3 -c \"from pyrogram import Client; Client('{TG_USERBOT_SESSION}',{API_ID},'{API_HASH}').run()\"")
        return False
    await _userbot.start()
    print("✅ یوزربات تلگرام متصل شد.")
    return True
