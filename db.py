"""
db.py — مدیریت دیتابیس SQLite برای پروژه Tele2Rub
"""

import sqlite3
import time
import random
import string
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "tele2rub.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """ایجاد جداول دیتابیس در صورت نبود"""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id     INTEGER PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                last_name       TEXT,
                joined_at       REAL NOT NULL,
                total_bytes     INTEGER DEFAULT 0,
                sub_active      INTEGER DEFAULT 0,
                sub_expires     REAL
            );

            CREATE TABLE IF NOT EXISTS files (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_code             TEXT UNIQUE NOT NULL,
                telegram_user_id        INTEGER NOT NULL,
                file_name               TEXT,
                file_size               INTEGER DEFAULT 0,
                archive_path            TEXT,
                rubika_channel_guid     TEXT,
                rubika_message_id       TEXT,
                created_at              REAL NOT NULL,
                delivered               INTEGER DEFAULT 0,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS forward_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_code     TEXT NOT NULL,
                rubika_user_id  TEXT NOT NULL,
                created_at      REAL NOT NULL,
                status          TEXT DEFAULT 'pending',
                error           TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_files_code ON files(unique_code);
            CREATE INDEX IF NOT EXISTS idx_fwd_status ON forward_queue(status);
        """)


# ─── کاربران ──────────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, username: str, first_name: str, last_name: str):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE users
                   SET username=?, first_name=?, last_name=?
                   WHERE telegram_id=?""",
                (username, first_name, last_name, telegram_id),
            )
        else:
            conn.execute(
                """INSERT INTO users (telegram_id, username, first_name, last_name, joined_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (telegram_id, username, first_name, last_name, time.time()),
            )


def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


def add_bytes_used(telegram_id: int, size: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET total_bytes = total_bytes + ? WHERE telegram_id = ?",
            (size, telegram_id),
        )


def set_subscription(telegram_id: int, active: bool, expires_ts: Optional[float] = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET sub_active=?, sub_expires=? WHERE telegram_id=?",
            (1 if active else 0, expires_ts, telegram_id),
        )


def is_subscribed(telegram_id: int) -> bool:
    user = get_user(telegram_id)
    if not user:
        return False
    if not user["sub_active"]:
        return False
    if user["sub_expires"] and user["sub_expires"] < time.time():
        # اشتراک منقضی شده — غیرفعال کن
        set_subscription(telegram_id, False)
        return False
    return True


# ─── فایل‌ها ───────────────────────────────────────────────────────────────────

def _gen_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def create_file_record(
    telegram_user_id: int,
    file_name: str,
    file_size: int,
    archive_path: str,
) -> str:
    """یک رکورد فایل جدید با کد یونیک می‌سازد و کد را برمی‌گرداند"""
    with get_conn() as conn:
        for _ in range(10):
            code = _gen_code()
            try:
                conn.execute(
                    """INSERT INTO files
                       (unique_code, telegram_user_id, file_name, file_size,
                        archive_path, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (code, telegram_user_id, file_name, file_size,
                     archive_path, time.time()),
                )
                return code
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("نتونستم کد یونیک بسازم. دوباره امتحان کن.")


def update_rubika_info(unique_code: str, channel_guid: str, message_id: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE files
               SET rubika_channel_guid=?, rubika_message_id=?
               WHERE unique_code=?""",
            (channel_guid, message_id, unique_code),
        )


def get_file_by_code(unique_code: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM files WHERE unique_code = ?", (unique_code.upper(),)
        ).fetchone()


def mark_delivered(unique_code: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE files SET delivered=1 WHERE unique_code=?", (unique_code,)
        )


# ─── صف فوروارد ────────────────────────────────────────────────────────────────

def push_forward(unique_code: str, rubika_user_id: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO forward_queue (unique_code, rubika_user_id, created_at)
               VALUES (?, ?, ?)""",
            (unique_code.upper(), rubika_user_id, time.time()),
        )


def pop_forward() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM forward_queue WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE forward_queue SET status='processing' WHERE id=?", (row["id"],)
            )
        return row


def complete_forward(fwd_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE forward_queue SET status='done' WHERE id=?", (fwd_id,)
        )


def fail_forward(fwd_id: int, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE forward_queue SET status='failed', error=? WHERE id=?",
            (error, fwd_id),
        )


# ─── ابزارهای نمایش ──────────────────────────────────────────────────────────

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


# اجرای اولیه
init_db()
