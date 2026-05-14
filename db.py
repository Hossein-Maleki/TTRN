"""
db.py — مدیریت دیتابیس SQLite برای پروژه Tele2Rub
نسخه ۲.۰ — با پشتیبانی از اشتراک، سفارش، آمار و صف‌های توسعه‌یافته
"""

import sqlite3
import time
import random
import string
import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH  = BASE_DIR / "data" / "tele2rub.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

GIFT_BYTES = 200 * 1024 * 1024    # ۲۰۰ مگ هدیه اولیه برای همه کاربران
FREE_LIMIT = 20  * 1024 * 1024    # سقف هر فایل برای کاربر بدون پلن پولی

PLANS = [
    {"key": "1g",  "name": "۱ گیگ",  "bytes": 1  * 1024**3, "amount": 25_000,  "days": 30},
    {"key": "3g",  "name": "۳ گیگ",  "bytes": 3  * 1024**3, "amount": 60_000,  "days": 30},
    {"key": "5g",  "name": "۵ گیگ",  "bytes": 5  * 1024**3, "amount": 100_000, "days": 30},
    {"key": "10g", "name": "۱۰ گیگ", "bytes": 10 * 1024**3, "amount": 290_000, "days": 30},
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                username      TEXT    DEFAULT '',
                first_name    TEXT    DEFAULT '',
                last_name     TEXT    DEFAULT '',
                joined_at     REAL    NOT NULL,
                total_bytes   INTEGER DEFAULT 0,
                bytes_quota   INTEGER DEFAULT 209715200,
                bytes_used    INTEGER DEFAULT 0,
                sub_active    INTEGER DEFAULT 0,
                sub_expires   REAL,
                sub_plan      TEXT    DEFAULT '',
                safe_mode     INTEGER DEFAULT 0,
                zip_password  TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS files (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_code         TEXT    UNIQUE NOT NULL,
                telegram_user_id    INTEGER NOT NULL,
                file_name           TEXT,
                file_size           INTEGER DEFAULT 0,
                archive_path        TEXT,
                rubika_channel_guid TEXT,
                rubika_message_id   TEXT,
                created_at          REAL    NOT NULL,
                delivered           INTEGER DEFAULT 0,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS forward_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_code     TEXT,
                rubika_user_id  TEXT    NOT NULL,
                created_at      REAL    NOT NULL,
                status          TEXT    DEFAULT 'pending',
                error           TEXT,
                text_content    TEXT,
                forward_type    TEXT    DEFAULT 'file'
            );

            CREATE TABLE IF NOT EXISTS orders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL,
                plan_key        TEXT    NOT NULL,
                plan_name       TEXT    NOT NULL,
                plan_bytes      INTEGER NOT NULL,
                plan_days       INTEGER NOT NULL,
                amount          INTEGER NOT NULL,
                tx_code         TEXT    UNIQUE NOT NULL,
                status          TEXT    DEFAULT 'pending',
                receipt_file_id TEXT,
                created_at      REAL    NOT NULL,
                reviewed_at     REAL,
                admin_note      TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS tg_fetch_queue (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                rubika_user_id   TEXT    NOT NULL,
                telegram_user_id INTEGER,
                request_type     TEXT    NOT NULL,
                channel          TEXT,
                post_id          INTEGER,
                query            TEXT,
                status           TEXT    DEFAULT 'pending',
                result           TEXT,
                created_at       REAL    NOT NULL,
                error            TEXT
            );

            CREATE TABLE IF NOT EXISTS joined_channels (
                rubika_user_id TEXT NOT NULL,
                channel_id     TEXT NOT NULL,
                invite_link    TEXT,
                joined_at      REAL NOT NULL,
                PRIMARY KEY (rubika_user_id, channel_id)
            );

            CREATE INDEX IF NOT EXISTS idx_files_code    ON files(unique_code);
            CREATE INDEX IF NOT EXISTS idx_fwd_status    ON forward_queue(status);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_fetch_status  ON tg_fetch_queue(status);
            CREATE INDEX IF NOT EXISTS idx_orders_tid    ON orders(telegram_id);
        """)
        defaults = [
            ("card_number",    "6037-XXXX-XXXX-XXXX"),
            ("card_holder",    "نام دارنده کارت"),
            ("support_username", "@admin"),
            ("bot_username",   "@YourRubikaBot"),
        ]
        for k, v in defaults:
            conn.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))
    _migrate()


def _migrate():
    """مهاجرت ساختار دیتابیس قدیمی"""
    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        migrations = [
            ("bytes_quota",  "INTEGER", "209715200"),
            ("bytes_used",   "INTEGER", "0"),
            ("sub_plan",     "TEXT",    "''"),
            ("safe_mode",    "INTEGER", "0"),
            ("zip_password", "TEXT",    "''"),
        ]
        for col, typ, defval in migrations:
            if col not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typ} DEFAULT {defval}")

        fwd_cols = {r[1] for r in conn.execute("PRAGMA table_info(forward_queue)")}
        if "text_content" not in fwd_cols:
            conn.execute("ALTER TABLE forward_queue ADD COLUMN text_content TEXT")
        if "forward_type" not in fwd_cols:
            conn.execute("ALTER TABLE forward_queue ADD COLUMN forward_type TEXT DEFAULT 'file'")


# ═══════════════════════════════════════════════════════════════════════════════
#  کاربران
# ═══════════════════════════════════════════════════════════════════════════════

def upsert_user(telegram_id: int, username: str, first_name: str, last_name: str):
    with get_conn() as conn:
        row = conn.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, last_name=? WHERE telegram_id=?",
                (username, first_name, last_name, telegram_id),
            )
        else:
            conn.execute(
                "INSERT INTO users (telegram_id,username,first_name,last_name,joined_at,bytes_quota) VALUES (?,?,?,?,?,?)",
                (telegram_id, username, first_name, last_name, time.time(), GIFT_BYTES),
            )


def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()


def get_all_users(limit=100) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT ?", (limit,)
        ).fetchall()


def add_bytes_used(telegram_id: int, size: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET total_bytes=total_bytes+?, bytes_used=bytes_used+? WHERE telegram_id=?",
            (size, size, telegram_id),
        )


def set_subscription(telegram_id: int, active: bool,
                     expires_ts: Optional[float] = None,
                     plan_name: str = "", extra_bytes: int = 0):
    with get_conn() as conn:
        if active and extra_bytes:
            conn.execute(
                "UPDATE users SET sub_active=1, sub_expires=?, sub_plan=?, bytes_quota=bytes_quota+?, bytes_used=0 WHERE telegram_id=?",
                (expires_ts, plan_name, extra_bytes, telegram_id),
            )
        else:
            conn.execute(
                "UPDATE users SET sub_active=?, sub_expires=?, sub_plan=? WHERE telegram_id=?",
                (1 if active else 0, expires_ts, plan_name, telegram_id),
            )


def update_safe_mode(telegram_id: int, enabled: bool, password: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET safe_mode=?, zip_password=? WHERE telegram_id=?",
            (1 if enabled else 0, password, telegram_id),
        )


def has_active_paid_plan(telegram_id: int) -> bool:
    user = get_user(telegram_id)
    if not user or not user["sub_active"]:
        return False
    if user["sub_expires"] and user["sub_expires"] < time.time():
        with get_conn() as conn:
            conn.execute("UPDATE users SET sub_active=0 WHERE telegram_id=?", (telegram_id,))
        return False
    return True


def check_quota(telegram_id: int, file_size: int) -> tuple:
    """بررسی سهمیه — برمی‌گرداند (ok: bool, reason: str)"""
    user = get_user(telegram_id)
    if not user:
        return False, "کاربر یافت نشد."
    remaining = user["bytes_quota"] - user["bytes_used"]
    if remaining <= 0:
        return False, "⛔ سهمیه شما تمام شده!\nبرای ادامه اشتراک بخرید: /buy"
    if file_size > remaining:
        return False, (
            f"⛔ حجم فایل ({pretty_size(file_size)}) از سهمیه باقی‌مانده "
            f"({pretty_size(remaining)}) بیشتر است.\nخرید اشتراک: /buy"
        )
    if not has_active_paid_plan(telegram_id) and file_size > FREE_LIMIT:
        return False, (
            f"⛔ فایل‌های بیش از {pretty_size(FREE_LIMIT)} نیاز به پلن پولی دارند.\n"
            f"خرید اشتراک: /buy"
        )
    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
#  تنظیمات
# ═══════════════════════════════════════════════════════════════════════════════

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))


# ═══════════════════════════════════════════════════════════════════════════════
#  سفارش‌ها
# ═══════════════════════════════════════════════════════════════════════════════

def _gen_tx() -> str:
    return "TX" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def create_order(telegram_id: int, plan: dict) -> str:
    with get_conn() as conn:
        for _ in range(10):
            code = _gen_tx()
            try:
                conn.execute(
                    "INSERT INTO orders (telegram_id,plan_key,plan_name,plan_bytes,plan_days,amount,tx_code,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (telegram_id, plan["key"], plan["name"], plan["bytes"], plan["days"], plan["amount"], code, time.time()),
                )
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("خطا در ساخت سفارش.")


def get_order(order_id: int = None, tx_code: str = None) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        if order_id:
            return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if tx_code:
            return conn.execute("SELECT * FROM orders WHERE tx_code=?", (tx_code,)).fetchone()
    return None


def get_orders_by_status(status: str = None, limit: int = 30) -> list:
    with get_conn() as conn:
        if status:
            return conn.execute(
                "SELECT o.*,u.first_name,u.username FROM orders o LEFT JOIN users u ON o.telegram_id=u.telegram_id WHERE o.status=? ORDER BY o.id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return conn.execute(
            "SELECT o.*,u.first_name,u.username FROM orders o LEFT JOIN users u ON o.telegram_id=u.telegram_id ORDER BY o.id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def set_order_receipt(order_id: int, receipt_file_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE orders SET receipt_file_id=? WHERE id=?", (receipt_file_id, order_id))


def approve_order(order_id: int, admin_note: str = "") -> bool:
    order = get_order(order_id=order_id)
    if not order or order["status"] != "pending":
        return False
    expires = time.time() + order["plan_days"] * 86400
    set_subscription(order["telegram_id"], True, expires, order["plan_name"], order["plan_bytes"])
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status='approved', reviewed_at=?, admin_note=? WHERE id=?",
            (time.time(), admin_note, order_id),
        )
    return True


def reject_order(order_id: int, admin_note: str = "") -> bool:
    if not get_order(order_id=order_id):
        return False
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status='rejected', reviewed_at=?, admin_note=? WHERE id=?",
            (time.time(), admin_note, order_id),
        )
    return True


def get_user_pending_order(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE telegram_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (telegram_id,),
        ).fetchone()


# ═══════════════════════════════════════════════════════════════════════════════
#  فایل‌ها
# ═══════════════════════════════════════════════════════════════════════════════

def _gen_code(length=8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def create_file_record(telegram_user_id: int, file_name: str,
                        file_size: int, archive_path: str) -> str:
    with get_conn() as conn:
        for _ in range(10):
            code = _gen_code()
            try:
                conn.execute(
                    "INSERT INTO files (unique_code,telegram_user_id,file_name,file_size,archive_path,created_at) VALUES (?,?,?,?,?,?)",
                    (code, telegram_user_id, file_name, file_size, archive_path, time.time()),
                )
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("خطا در ساخت کد یونیک.")


def update_rubika_info(unique_code: str, channel_guid: str, message_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE files SET rubika_channel_guid=?, rubika_message_id=? WHERE unique_code=?",
            (channel_guid, message_id, unique_code),
        )


def get_file_by_code(unique_code: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM files WHERE unique_code=?", (unique_code.upper(),)).fetchone()


def mark_delivered(unique_code: str):
    with get_conn() as conn:
        conn.execute("UPDATE files SET delivered=1 WHERE unique_code=?", (unique_code,))


# ═══════════════════════════════════════════════════════════════════════════════
#  صف فوروارد (ربات روبیکا → کاربر)
# ═══════════════════════════════════════════════════════════════════════════════

def push_forward(unique_code: str, rubika_user_id: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO forward_queue (unique_code,rubika_user_id,created_at,forward_type) VALUES (?,?,?,'file')",
            (unique_code.upper(), rubika_user_id, time.time()),
        )


def push_text_forward(rubika_user_id: str, text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO forward_queue (rubika_user_id,created_at,text_content,forward_type) VALUES (?,?,?,'text')",
            (rubika_user_id, time.time(), text),
        )


def pop_forward() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM forward_queue WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("UPDATE forward_queue SET status='processing' WHERE id=?", (row["id"],))
        return row


def complete_forward(fwd_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE forward_queue SET status='done' WHERE id=?", (fwd_id,))


def fail_forward(fwd_id: int, error: str):
    with get_conn() as conn:
        conn.execute("UPDATE forward_queue SET status='failed', error=? WHERE id=?", (error, fwd_id))


# ═══════════════════════════════════════════════════════════════════════════════
#  صف فچ تلگرام (یوزربات)
# ═══════════════════════════════════════════════════════════════════════════════

def push_tg_fetch(rubika_user_id: str, request_type: str,
                   channel=None, post_id=None, query=None,
                   telegram_user_id=None) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tg_fetch_queue (rubika_user_id,telegram_user_id,request_type,channel,post_id,query,created_at) VALUES (?,?,?,?,?,?,?)",
            (rubika_user_id, telegram_user_id, request_type, channel, post_id, query, time.time()),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def pop_tg_fetch() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tg_fetch_queue WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("UPDATE tg_fetch_queue SET status='processing' WHERE id=?", (row["id"],))
        return row


def complete_tg_fetch(fetch_id: int, result_json: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tg_fetch_queue SET status='done', result=? WHERE id=?", (result_json, fetch_id)
        )


def fail_tg_fetch(fetch_id: int, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tg_fetch_queue SET status='failed', error=? WHERE id=?", (error, fetch_id)
        )


def save_joined_channel(rubika_user_id: str, channel_id: str, invite_link: str = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO joined_channels (rubika_user_id,channel_id,invite_link,joined_at) VALUES (?,?,?,?)",
            (rubika_user_id, channel_id, invite_link, time.time()),
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  آمار
# ═══════════════════════════════════════════════════════════════════════════════

def get_stats() -> dict:
    now = time.time()
    with get_conn() as conn:
        total_users  = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_subs  = conn.execute(
            "SELECT COUNT(*) FROM users WHERE sub_active=1 AND (sub_expires IS NULL OR sub_expires>?)", (now,)
        ).fetchone()[0]
        total_files  = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        delivered    = conn.execute("SELECT COUNT(*) FROM files WHERE delivered=1").fetchone()[0]
        pending_ord  = conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
        appr_row     = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM orders WHERE status='approved'"
        ).fetchone()
        total_bytes  = conn.execute("SELECT COALESCE(SUM(total_bytes),0) FROM users").fetchone()[0]
        today_start  = datetime.datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        today_sales  = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='approved' AND reviewed_at>?", (today_start,)
        ).fetchone()[0]
        return {
            "total_users":    total_users,
            "active_subs":    active_subs,
            "total_files":    total_files,
            "delivered":      delivered,
            "pending_orders": pending_ord,
            "approved_count": appr_row[0],
            "total_revenue":  appr_row[1],
            "today_revenue":  today_sales,
            "total_bytes":    total_bytes,
        }

def remaining_quota_text(telegram_id: int) -> str:
    user = get_user(telegram_id)

    if not user:
        return "نامشخص"

    total = user["bytes_quota"] or 0
    used = user["bytes_used"] or 0
    remaining = max(0, total - used)

    percent = int((used / total) * 100) if total else 0

    plan = "💎 اشتراک فعال" if has_active_paid_plan(telegram_id) else "🎁 رایگان"

    return (
        f"{plan}\n"
        f"📦 مصرف شده: {pretty_size(used)}\n"
        f"💾 باقی‌مانده: {pretty_size(remaining)}\n"
        f"📊 {percent}% استفاده شده"
    )
# ═══════════════════════════════════════════════════════════════════════════════
#  ابزارهای نمایش
# ═══════════════════════════════════════════════════════════════════════════════

def pretty_size(size) -> str:
    size = float(size or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def pretty_time(ts) -> str:
    if not ts:
        return "—"
    dt = datetime.datetime.fromtimestamp(float(ts))
    return dt.strftime("%Y-%m-%d %H:%M")


# اجرای اولیه
init_db()
