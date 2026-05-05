"""
rub_worker.py — ورکر روبیکا: آپلود به کانال خصوصی + پردازش صف فوروارد
"""

import os
import re
import json
import time
import threading
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rubpy import Client as RubikaClient
import requests
import pyzipper
from urllib.parse import urlparse

import db

load_dotenv()

SESSION             = os.getenv("RUBIKA_SESSION", "rubika_session").strip()
RUBIKA_CHANNEL_GUID = os.getenv("RUBIKA_CHANNEL_GUID", "").strip()   # c0xxx...

BASE_DIR        = Path(__file__).resolve().parent
DOWNLOAD_DIR    = BASE_DIR / "downloads"
ARCHIVE_DIR     = BASE_DIR / "archive"
QUEUE_DIR       = BASE_DIR / "queue"
QUEUE_FILE      = QUEUE_DIR / "tasks.jsonl"
STATUS_FILE     = QUEUE_DIR / "status.jsonl"
CANCEL_FILE     = QUEUE_DIR / "cancelled.jsonl"
PROCESSING_FILE = QUEUE_DIR / "processing.json"
FAILED_FILE     = QUEUE_DIR / "failed.jsonl"
URL_DIR         = DOWNLOAD_DIR / "url"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR, URL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

MAX_RETRIES    = 5
UPLOAD_TIMEOUT = 1800


# ─── ابزارها ──────────────────────────────────────────────────────────────────

def safe_filename(name: Optional[str]) -> str:
    name = (name or "file").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.rstrip(". ")
    return name[:200] or "file"


def pretty_size(size) -> str:
    size = float(size or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def eta_text(seconds) -> str:
    if not seconds or seconds <= 0:
        return "نامشخص"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def get_per_attempt_timeout(file_path: str) -> int:
    size_mb = Path(file_path).stat().st_size / (1024 * 1024)
    if size_mb < 100:
        return 180
    elif size_mb < 500:
        return 420
    elif size_mb < 1000:
        return 720
    return 1200


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def push_status(task: dict, text: str, percent: float = None):
    payload = {
        "chat_id":    task.get("chat_id"),
        "message_id": task.get("status_message_id"),
        "text":       text,
        "percent":    percent,
        "time":       time.time(),
    }
    with open(STATUS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def is_cancelled(task: dict) -> bool:
    job_id = str(task.get("job_id", ""))
    if not job_id or not CANCEL_FILE.exists():
        return False
    with open(CANCEL_FILE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if str(item.get("job_id")) == job_id:
                return True
    return False


# ─── ارتباط با روبیکا ─────────────────────────────────────────────────────────

def has_session() -> bool:
    for suffix in ["", ".session", ".sqlite"]:
        if Path(f"{SESSION}{suffix}").exists():
            return True
    return False


def ensure_session():
    if has_session():
        return
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        print("✅ ورود به روبیکا موفق بود.")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def _send_document_sync(file_path: str, caption: str, target: str):
    """ارسال فایل به یک مقصد (channel guid یا user guid)"""
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        result = client.send_document(target, file_path, caption=caption or "")
        return result
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def send_with_timeout(file_path: str, caption: str, target: str, timeout: int):
    result = {}
    error  = {}

    def _run():
        try:
            result["data"] = _send_document_sync(file_path, caption, target)
        except Exception as e:
            error["err"] = e

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise RuntimeError("آپلود بیشتر از حد مجاز طول کشید.")
    if "err" in error:
        raise error["err"]
    return result.get("data")


def send_with_retry(file_path: str, caption: str, target: str, task: dict = None):
    last_error = None
    start_time = time.time()

    for attempt in range(1, MAX_RETRIES + 1):
        if time.time() - start_time > UPLOAD_TIMEOUT:
            raise RuntimeError("زمان آپلود به پایان رسید.")
        if task and is_cancelled(task):
            raise RuntimeError("ارسال لغو شد.")

        if task:
            push_status(
                task,
                f"🔼 **در حال آپلود در روبیکا...**\n\n"
                f"🔴 تلاش {attempt} از {MAX_RETRIES}\n"
                f"برای لغو: `/del {task.get('job_id')}`"
            )

        elapsed   = time.time() - start_time
        remaining = UPLOAD_TIMEOUT - elapsed
        if remaining <= 0:
            raise RuntimeError("زمان آپلود به پایان رسید.")

        per_attempt = min(get_per_attempt_timeout(file_path), remaining)

        try:
            result = send_with_timeout(file_path, caption, target, per_attempt)
            return result
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            transient = any(k in err_str for k in [
                "502", "503", "bad gateway", "timeout", "cannot connect",
                "connection reset", "temporarily unavailable",
                "error uploading chunk", "unexpected mimetype",
            ])
            if transient and attempt < MAX_RETRIES:
                if task:
                    push_status(task, f"⚠️ اتصال ناپایدار، دوباره تلاش می‌کنم ({attempt + 1})...")
                time.sleep(3)
                continue
            break

    raise last_error or RuntimeError("آپلود ناموفق بود.")


# ─── دانلود URL ────────────────────────────────────────────────────────────────

def download_url(task: dict) -> Path:
    url = task.get("url", "").strip()
    if not url:
        raise RuntimeError("URL خالی است.")

    push_status(task, "🌐 در حال دانلود از لینک مستقیم...", 0)

    try:
        resp = requests.get(url, stream=True, timeout=(10, 60), allow_redirects=True)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError("لینک جواب نداد.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("خطای شبکه.")
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response else "نامشخص"
        raise RuntimeError(f"دانلود ناموفق. کد: {code}")

    cd = resp.headers.get("content-disposition", "")
    match = re.findall(r'filename="(.+?)"', cd)
    name = match[0] if match else Path(urlparse(url).path).name
    name = safe_filename(name or f"file_{int(time.time())}")
    if "." not in name:
        name += ".bin"

    target    = unique_path(URL_DIR / name)
    total     = int(resp.headers.get("content-length") or 0)
    downloaded = 0
    last_upd   = 0
    started    = time.time()

    with open(target, "wb") as f:
        for chunk in resp.iter_content(1024 * 1024):
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if now - last_upd < 3 and downloaded < total:
                continue
            last_upd = now
            speed   = downloaded / max(now - started, 1)
            eta     = (total - downloaded) / speed if total and speed else None
            percent = downloaded * 100 / total if total else None
            text    = f"🌐 دانلود: {pretty_size(downloaded)}"
            if total:
                text += f" از {pretty_size(total)}"
            text += f"\n⚡ سرعت: {pretty_size(speed)}/s"
            if eta:
                text += f"\n⏳ مانده: {eta_text(eta)}"
            push_status(task, text, percent)

    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("فایل دانلود نشد.")

    # کپی به archive
    archive_path = ARCHIVE_DIR / name
    shutil.copy2(str(target), str(unique_path(archive_path)))

    task["file_name"]    = target.name
    task["file_size"]    = target.stat().st_size
    task["archive_path"] = str(unique_path(ARCHIVE_DIR / name))
    return target


# ─── ZIP رمزدار ───────────────────────────────────────────────────────────────

def make_zip(file_path: Path, password: str) -> Path:
    zip_path = unique_path(file_path.with_suffix(file_path.suffix + ".zip"))
    with pyzipper.AESZipFile(zip_path, "w",
                             compression=pyzipper.ZIP_STORED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode("utf-8"))
        zf.write(file_path, arcname=file_path.name)
    return zip_path


# ─── پردازش تسک ───────────────────────────────────────────────────────────────

def process_task(task: dict):
    task_type    = task.get("type")
    caption      = task.get("caption", "")
    safe_mode    = task.get("safe_mode", False)
    zip_password = task.get("zip_password", "")
    unique_code  = task.get("unique_code")
    channel_guid = RUBIKA_CHANNEL_GUID or "me"

    local_path: Path = None

    if task_type == "local_file":
        local_path = Path(task.get("path", ""))
        if not local_path.exists():
            # شاید archive داشته باشیم
            arch = task.get("archive_path")
            if arch and Path(arch).exists():
                local_path = Path(arch)
            else:
                raise RuntimeError("فایل محلی پیدا نشد.")
    elif task_type == "direct_url":
        local_path = download_url(task)
        # ثبت رکورد اگر URL است (unique_code نداریم)
        if not unique_code:
            unique_code = db.create_file_record(
                telegram_user_id=task.get("telegram_user_id", 0),
                file_name=task.get("file_name", local_path.name),
                file_size=task.get("file_size", local_path.stat().st_size),
                archive_path=task.get("archive_path", str(local_path)),
            )
            db.add_bytes_used(
                task.get("telegram_user_id", 0),
                task.get("file_size", local_path.stat().st_size)
            )
    else:
        raise RuntimeError("نوع تسک ناشناخته.")

    # رمزگذاری ZIP
    if safe_mode and zip_password:
        push_status(task, "🔒 در حال تبدیل به ZIP رمزدار...")
        try:
            zipped = make_zip(local_path, zip_password)
        finally:
            try:
                if local_path.exists() and local_path != Path(task.get("archive_path", "")):
                    local_path.unlink()
            except Exception:
                pass
        send_path = zipped
    else:
        send_path = local_path

    if is_cancelled(task):
        raise RuntimeError("ارسال لغو شد.")

    # آپلود به کانال خصوصی روبیکا
    result = send_with_retry(str(send_path), caption, channel_guid, task)

    # استخراج message_id از نتیجه
    rubika_message_id = None
    try:
        if result:
            # rubpy نتیجه رو به صورت dict یا object برمی‌گردونه
            if hasattr(result, "message_id"):
                rubika_message_id = str(result.message_id)
            elif isinstance(result, dict):
                rubika_message_id = str(
                    result.get("message_id") or
                    result.get("data", {}).get("message_id", "")
                )
    except Exception:
        pass

    # به‌روزرسانی دیتابیس با اطلاعات روبیکا
    if unique_code:
        db.update_rubika_info(unique_code, channel_guid, rubika_message_id or "")

    # پاکسازی فایل ارسالی (نه archive)
    try:
        if send_path != Path(task.get("archive_path", "")) and send_path.exists():
            send_path.unlink()
    except Exception:
        pass

    # اگر local_path همان archive نیست، پاکش کن
    try:
        lp = Path(task.get("path", ""))
        if lp.exists() and lp != Path(task.get("archive_path", "")):
            lp.unlink()
    except Exception:
        pass

    code_display = unique_code or "—"
    push_status(
        task,
        f"✅ **فایل با موفقیت در روبیکا آپلود شد!**\n\n"
        f"🎫 **کد یونیک:** `{code_display}`\n\n"
        f"این کد رو در ربات روبیکا وارد کن تا فایل برات ارسال بشه."
    )


# ─── صف اصلی ─────────────────────────────────────────────────────────────────

def pop_first_task():
    if not QUEUE_FILE.exists():
        return None
    with open(QUEUE_FILE, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    if not lines:
        return None
    first = lines[0]
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines[1:])
    return json.loads(first)


def save_processing(task: dict):
    with open(PROCESSING_FILE, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)


def clear_processing():
    try:
        PROCESSING_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def append_failed(task: dict, error: str):
    with open(FAILED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"task": task, "error": error}, ensure_ascii=False) + "\n")


# ─── صف فوروارد (ربات روبیکا → کاربر روبیکا) ─────────────────────────────────

def process_forward_queue():
    """پردازش درخواست‌های فوروارد از ربات روبیکا به کاربران"""
    while True:
        time.sleep(1)
        fwd = db.pop_forward()
        if not fwd:
            continue
        try:
            file_record = db.get_file_by_code(fwd["unique_code"])
            if not file_record:
                db.fail_forward(fwd["id"], "کد پیدا نشد.")
                continue

            archive_path = file_record["archive_path"]
            if not archive_path or not Path(archive_path).exists():
                db.fail_forward(fwd["id"], "فایل archive پیدا نشد.")
                continue

            rubika_user_id = fwd["rubika_user_id"]
            _send_document_sync(
                file_path=archive_path,
                caption=f"🎫 کد: {fwd['unique_code']}\n📄 {file_record['file_name']}",
                target=rubika_user_id,
            )
            db.complete_forward(fwd["id"])
            db.mark_delivered(fwd["unique_code"])

        except Exception as e:
            db.fail_forward(fwd["id"], str(e))


# ─── اجرا ─────────────────────────────────────────────────────────────────────

def worker_loop():
    ensure_session()
    print("✅ ورکر روبیکا شروع به کار کرد.")

    # thread جداگانه برای صف فوروارد
    fwd_thread = threading.Thread(target=process_forward_queue, daemon=True)
    fwd_thread.start()

    while True:
        task = pop_first_task()
        if not task:
            time.sleep(0.3)
            continue

        save_processing(task)
        try:
            process_task(task)
        except Exception as e:
            append_failed(task, str(e))
            push_status(task, f"❌ خطا: {str(e)}")
        finally:
            clear_processing()


if __name__ == "__main__":
    worker_loop()
