import sqlite3
import time
import random
import string
from pathlib import Path
from typing import Optional, List, Dict, Any
import threading

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "tele2rub.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# قفل برای جلوگیری از تداخل در نوشتن همزمان (Thread-safe)
db_lock = threading.Lock()

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """ایجاد جداول مورد نیاز با ساختار جدید"""
    with db_lock:
        conn = get_connection()
        # جدول کاربران
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                bytes_quota INTEGER DEFAULT 209715200, -- 200MB هدیه
                bytes_used INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                safe_mode INTEGER DEFAULT 0,
                zip_password TEXT DEFAULT '',
                created_at REAL
            )
        """)

        # جدول فایل‌ها - ارتقا یافته برای روبیکا
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_code TEXT UNIQUE,          -- کد ۸ رقمی برای کاربر
                telegram_user_id INTEGER,
                file_name TEXT,
                file_size INTEGER,
                caption TEXT,
                rubika_channel_guid TEXT,         -- GUID کانالی که فایل در آن آپلود شده
                rubika_message_id TEXT,           -- ID پیام در روبیکا برای فوروارد آنی
                status TEXT DEFAULT 'pending',    -- pending, uploaded, delivered
                created_at REAL,
                delivered_at REAL
            )
        """)

        # جدول تنظیمات سیستمی
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # مقادیر اولیه تنظیمات
        default_settings = [
            ('rubika_account_username', '@YourAccount'),
            ('support_username', '@AdminSupport'),
            ('channel_link', 'https://rubika.ir/your_channel')
        ]
        conn.executemany("INSERT OR IGNORE INTO settings VALUES (?, ?)", default_settings)
        
        conn.commit()
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  مدیریت کاربران
# ═══════════════════════════════════════════════════════════════════════════════

def upsert_user(user_id, username, first_name, last_name):
    with db_lock:
        conn = get_connection()
        conn.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name
        """, (user_id, username, first_name, last_name, time.time()))
        conn.commit()
        conn.close()

def get_user(user_id) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

# ═══════════════════════════════════════════════════════════════════════════════
#  مدیریت فایل‌ها و کدهای یونیک (هسته اصلی ربات)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_unique_code(length=8):
    """تولید کد منحصر به فرد که در دیتابیس نباشد"""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        conn = get_connection()
        exists = conn.execute("SELECT 1 FROM files WHERE unique_code = ?", (code,)).fetchone()
        conn.close()
        if not exists:
            return code

def create_file_record(user_id, file_name, file_size, caption):
    """ایجاد رکورد اولیه فایل و دریافت کد یونیک"""
    code = generate_unique_code()
    with db_lock:
        conn = get_connection()
        conn.execute("""
            INSERT INTO files (unique_code, telegram_user_id, file_name, file_size, caption, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (code, user_id, file_name, file_size, caption, time.time()))
        conn.commit()
        conn.close()
    return code

def update_rubika_info(unique_code, guid, message_id):
    """ذخیره اطلاعات پس از آپلود در روبیکا برای فوروارد سریع"""
    with db_lock:
        conn = get_connection()
        conn.execute("""
            UPDATE files SET 
                rubika_channel_guid = ?, 
                rubika_message_id = ?, 
                status = 'uploaded' 
            WHERE unique_code = ?
        """, (guid, str(message_id), unique_code))
        conn.commit()
        conn.close()

def get_file_by_code(code: str) -> Optional[dict]:
    """جستجوی فایل بر اساس کدی که کاربر در روبیکا می‌فرستد"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM files WHERE unique_code = ?", (code.upper(),)).fetchone()
    conn.close()
    return dict(row) if row else None

def mark_delivered(code: str):
    """تغییر وضعیت فایل به تحویل داده شده"""
    with db_lock:
        conn = get_connection()
        conn.execute("""
            UPDATE files SET status = 'delivered', delivered_at = ? WHERE unique_code = ?
        """, (time.time(), code.upper()))
        conn.commit()
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  تنظیمات و آمار
# ═══════════════════════════════════════════════════════════════════════════════

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key: str, value: str):
    with db_lock:
        conn = get_connection()
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()

def get_stats():
    """دریافت آمار کلی برای پنل ادمین"""
    conn = get_connection()
    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "files_total": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "files_delivered": conn.execute("SELECT COUNT(*) FROM files WHERE status='delivered'").fetchone()[0],
        "total_traffic": conn.execute("SELECT SUM(file_size) FROM files").fetchone()[0] or 0
    }
    conn.close()
    return stats

# مقداردهی اولیه هنگام ایمپورت شدن
init_db()