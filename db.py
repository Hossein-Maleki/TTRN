
import sqlite3
import time
import random
import string
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH  = BASE_DIR / "data" / "tele2rub.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

FREE_GIFT_BYTES = 200 * 1024 * 1024  # 200 MB

PLANS: List[Dict] = [
    {"id": 1, "name": "۱ گیگ",  "size_bytes": 1  * 1024**3, "price": 25_000,  "days": 30},
    {"id": 2, "name": "۳ گیگ",  "size_bytes": 3  * 1024**3, "price": 60_000,  "days": 30},
    {"id": 3, "name": "۵ گیگ",  "size_bytes": 5  * 1024**3, "price": 100_000, "days": 30},
    {"id": 4, "name": "۱۰ گیگ", "size_bytes": 10 * 1024**3, "price": 290_000, "days": 30},
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id         INTEGER PRIMARY KEY,
                username            TEXT    DEFAULT '',
                first_name          TEXT    DEFAULT '',
                last_name           TEXT    DEFAULT '',
                joined_at           REAL    NOT NULL,
                total_bytes         INTEGER DEFAULT 0,
                bytes_period_used   INTEGER DEFAULT 0,
                quota_bytes         INTEGER DEFAULT 209715200,
                sub_active          INTEGER DEFAULT 1,
                sub_expires         REAL
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
                unique_code     TEXT    NOT NULL,
                rubika_user_id  TEXT    NOT NULL,
                created_at      REAL    NOT NULL,
                status          TEXT    DEFAULT 'pending',
                error           TEXT
            );

            CREATE TABLE IF NOT EXISTS payment_settings (
                id          INTEGER PRIMARY KEY CHECK(id = 1),
                card_number TEXT    DEFAULT '6037-xxxx-xxxx-xxxx',
                card_holder TEXT    DEFAULT 'نام صاحب کارت',
                bank_name   TEXT    DEFAULT 'نام بانک'
            );

            CREATE TABLE IF NOT EXISTS orders (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                plan_id          INTEGER NOT NULL,
                plan_name        TEXT    NOT NULL,
                plan_size_bytes  INTEGER NOT NULL,
                amount           INTEGER NOT NULL,
                tx_code          TEXT    UNIQUE NOT NULL,
                status           TEXT    DEFAULT 'pending',
                receipt_file_id  TEXT,
                admin_note       TEXT,
                created_at       REAL    NOT NULL,
                processed_at     REAL,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS rubika_tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                rubika_user_id  TEXT    NOT NULL,
                task_type       TEXT    NOT NULL,
                task_data       TEXT    DEFAULT '{}',
                status          TEXT    DEFAULT 'pending',
                created_at      REAL    NOT NULL,
                error           TEXT
            );

            CREATE TABLE IF NOT EXISTS channel_access (
                channel   TEXT PRIMARY KEY,
                joined_at REAL NOT NULL
            );

            INSERT OR IGNORE INTO payment_settings (id) VALUES (1);

            CREATE INDEX IF NOT EXISTS idx_files_code     ON files(unique_code);
            CREATE INDEX IF NOT EXISTS idx_fwd_status     ON forward_queue(status);
            CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_rtasks_status  ON rubika_tasks(status);
        """)
        # ستون‌های جدید روی جداول قدیمی
        for col_sql in [
            "ALTER TABLE users ADD COLUMN bytes_period_used INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN quota_bytes INTEGER DEFAULT 209715200",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass


# ────────────────────────────── کاربران ──────────────────────────────────────

def upsert_user(telegram_id: int, username: str, first_name: str, last_name: str):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, last_name=? WHERE telegram_id=?",
                (username, first_name, last_name, telegram_id),
            )
        else:
            conn.execute(
                """INSERT INTO users
                   (telegram_id,username,first_name,last_name,joined_at,quota_bytes,sub_active)
                   VALUES (?,?,?,?,?,?,1)""",
                (telegram_id, username, first_name, last_name, time.time(), FREE_GIFT_BYTES),
            )


def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()


def add_bytes_used(telegram_id: int, size: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET total_bytes=total_bytes+?, bytes_period_used=bytes_period_used+? WHERE telegram_id=?",
            (size, size, telegram_id),
        )


def set_subscription(telegram_id: int, active: bool, expires_ts: Optional[float] = None,
                     quota_bytes: Optional[int] = None):
    with get_conn() as conn:
        if quota_bytes is not None:
            conn.execute(
                "UPDATE users SET sub_active=?,sub_expires=?,quota_bytes=?,bytes_period_used=0 WHERE telegram_id=?",
                (1 if active else 0, expires_ts, quota_bytes, telegram_id),
            )
        else:
            conn.execute(
                "UPDATE users SET sub_active=?,sub_expires=? WHERE telegram_id=?",
                (1 if active else 0, expires_ts, telegram_id),
            )


def is_subscribed(telegram_id: int) -> bool:
    user = get_user(telegram_id)
    if not user:
        return False
    if not user["sub_active"]:
        return False
    if user["sub_expires"] and user["sub_expires"] < time.time():
        set_subscription(telegram_id, False)
        return False
    # بررسی سقف مصرف
    quota = user["quota_bytes"] or FREE_GIFT_BYTES
    used  = user["bytes_period_used"] or 0
    return used < quota


def has_quota(telegram_id: int, needed: int = 0) -> bool:
    """آیا کاربر به اندازه کافی سهمیه دارد؟"""
    user = get_user(telegram_id)
    if not user:
        return False
    if not user["sub_active"]:
        return False
    if user["sub_expires"] and user["sub_expires"] < time.time():
        set_subscription(telegram_id, False)
        return False
    quota = user["quota_bytes"] or FREE_GIFT_BYTES
    used  = user["bytes_period_used"] or 0
    return (quota - used) >= needed


def get_all_users(limit: int = 100, offset: int = 0) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()


def count_users() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ────────────────────────────── فایل‌ها ──────────────────────────────────────

def _gen_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def create_file_record(telegram_user_id: int, file_name: str,
                       file_size: int, archive_path: str) -> str:
    with get_conn() as conn:
        for _ in range(10):
            code = _gen_code()
            try:
                conn.execute(
                    """INSERT INTO files
                       (unique_code,telegram_user_id,file_name,file_size,archive_path,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (code, telegram_user_id, file_name, file_size, archive_path, time.time()),
                )
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("خطا در ساخت کد یونیک.")


def update_rubika_info(unique_code: str, channel_guid: str, message_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE files SET rubika_channel_guid=?,rubika_message_id=? WHERE unique_code=?",
            (channel_guid, message_id, unique_code),
        )


def get_file_by_code(unique_code: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM files WHERE unique_code=?", (unique_code.upper(),)
        ).fetchone()


def mark_delivered(unique_code: str):
    with get_conn() as conn:
        conn.execute("UPDATE files SET delivered=1 WHERE unique_code=?", (unique_code,))


# ────────────────────────────── forward_queue ─────────────────────────────────

def push_forward(unique_code: str, rubika_user_id: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO forward_queue (unique_code,rubika_user_id,created_at) VALUES (?,?,?)",
            (unique_code.upper(), rubika_user_id, time.time()),
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
        conn.execute(
            "UPDATE forward_queue SET status='failed',error=? WHERE id=?", (error, fwd_id)
        )


# ────────────────────────────── rubika_tasks ─────────────────────────────────

def push_rubika_task(rubika_user_id: str, task_type: str, task_data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO rubika_tasks (rubika_user_id,task_type,task_data,created_at) VALUES (?,?,?,?)",
            (rubika_user_id, task_type, json.dumps(task_data, ensure_ascii=False), time.time()),
        )
        return cur.lastrowid


def pop_rubika_task() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM rubika_tasks WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("UPDATE rubika_tasks SET status='processing' WHERE id=?", (row["id"],))
        return row


def complete_rubika_task(task_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE rubika_tasks SET status='done' WHERE id=?", (task_id,))


def fail_rubika_task(task_id: int, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE rubika_tasks SET status='failed',error=? WHERE id=?", (error, task_id)
        )


# ────────────────────────────── payment_settings ─────────────────────────────

def get_payment_settings() -> sqlite3.Row:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM payment_settings WHERE id=1").fetchone()


def update_payment_settings(card_number: str, card_holder: str, bank_name: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payment_settings SET card_number=?,card_holder=?,bank_name=? WHERE id=1",
            (card_number, card_holder, bank_name),
        )


# ────────────────────────────── orders ───────────────────────────────────────

def _gen_tx_code() -> str:
    return "TX" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def create_order(telegram_user_id: int, plan_id: int) -> Dict:
    plan = next((p for p in PLANS if p["id"] == plan_id), None)
    if not plan:
        raise ValueError("پلن نامعتبر")
    with get_conn() as conn:
        for _ in range(10):
            tx = _gen_tx_code()
            try:
                cur = conn.execute(
                    """INSERT INTO orders
                       (telegram_user_id,plan_id,plan_name,plan_size_bytes,amount,tx_code,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (telegram_user_id, plan_id, plan["name"], plan["size_bytes"],
                     plan["price"], tx, time.time()),
                )
                return {"order_id": cur.lastrowid, "tx_code": tx, "plan": plan}
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("خطا در ساخت سفارش")


def set_order_receipt(order_id: int, receipt_file_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET receipt_file_id=? WHERE id=?", (receipt_file_id, order_id)
        )


def confirm_order(order_id: int, admin_note: str = ""):
    with get_conn() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return None
        conn.execute(
            "UPDATE orders SET status='confirmed',admin_note=?,processed_at=? WHERE id=?",
            (admin_note, time.time(), order_id),
        )
        # فعال‌سازی اشتراک کاربر
        expires = time.time() + 30 * 86400
        conn.execute(
            """UPDATE users
               SET sub_active=1, sub_expires=?,
                   quota_bytes=quota_bytes+?,
                   bytes_period_used=0
               WHERE telegram_id=?""",
            (expires, order["plan_size_bytes"], order["telegram_user_id"]),
        )
        return dict(order)


def reject_order(order_id: int, admin_note: str = ""):
    with get_conn() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return None
        conn.execute(
            "UPDATE orders SET status='rejected',admin_note=?,processed_at=? WHERE id=?",
            (admin_note, time.time(), order_id),
        )
        return dict(order)


def get_pending_orders() -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE status='pending' ORDER BY created_at"
        ).fetchall()


def get_order(order_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


def get_orders_stats() -> Dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        confirmed = conn.execute("SELECT COUNT(*) FROM orders WHERE status='confirmed'").fetchone()[0]
        pending   = conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
        revenue   = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='confirmed'"
        ).fetchone()[0]
        return {"total": total, "confirmed": confirmed, "pending": pending, "revenue": revenue}


def get_recent_orders(limit: int = 20) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()


# ────────────────────────────── channel_access ───────────────────────────────

def save_channel_access(channel: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO channel_access (channel,joined_at) VALUES (?,?)",
            (channel, time.time()),
        )


def has_channel_access(channel: str) -> bool:
    with get_conn() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM channel_access WHERE channel=?", (channel,)
        ).fetchone())


# ────────────────────────────── ابزارهای نمایش ───────────────────────────────

def pretty_size(size: int) -> str:
    size = float(size or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def pretty_time(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    import datetime
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M")


def remaining_quota_text(user: sqlite3.Row) -> str:
    quota = user["quota_bytes"] or FREE_GIFT_BYTES
    used  = user["bytes_period_used"] or 0
    rem   = max(0, quota - used)
    pct   = min(100, used * 100 / quota) if quota else 0
    bar_len = 10
    filled  = int(bar_len * pct / 100)
    bar     = "█" * filled + "░" * (bar_len - filled)
    return (
        f"`{bar}` {pct:.0f}%\n"
        f"مصرف: `{pretty_size(used)}`\n"
        f"سقف: `{pretty_size(quota)}`\n"
        f"باقی‌مانده: `{pretty_size(rem)}`"
    )


init_db()
