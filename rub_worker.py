"""
rub_worker.py — ورکر روبیکا v2 - رفع‌شده
آپلود فایل، صف فوروارد، تسک‌های ربات روبیکا (لینک/جستجو/getpost)
"""

import os, re, json, time, threading, shutil, asyncio
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rubpy import Client as RubikaClient
import requests
import pyzipper
from urllib.parse import urlparse

import db
import tg_userbot as tgu

load_dotenv()

SESSION             = os.getenv("RUBIKA_SESSION", "rubika_session").strip()
RUBIKA_CHANNEL_GUID = os.getenv("RUBIKA_CHANNEL_GUID", "").strip()

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


# ───────────────────────────── ابزارها ───────────────────────────────────────

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
    if h: return f"{h}h {m}m"
    if m: return f"{m}m {s}s"
    return f"{s}s"


def get_per_attempt_timeout(file_path: str) -> int:
    size_mb = Path(file_path).stat().st_size / (1024 * 1024)
    if size_mb < 100:   return 180
    elif size_mb < 500: return 420
    elif size_mb < 1000:return 720
    return 1200


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        c = path.with_name(f"{stem}_{i}{suffix}")
        if not c.exists():
            return c
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


# ───────────────────────── ارتباط با روبیکا ──────────────────────────────────

def has_rubika_session() -> bool:
    for suffix in ["", ".session", ".sqlite"]:
        if Path(f"{SESSION}{suffix}").exists():
            return True
    return False


def ensure_session():
    if has_rubika_session():
        return
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        print("✅ ورود به روبیکا موفق.")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def _send_document_sync(file_path: str, caption: str, target: str):
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


def _send_text_sync(text: str, target: str):
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        client.send_message(target, text)
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def send_with_timeout(file_path: str, caption: str, target: str, timeout: int):
    result, error = {}, {}

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

        elapsed    = time.time() - start_time
        remaining  = UPLOAD_TIMEOUT - elapsed
        if remaining <= 0:
            raise RuntimeError("زمان آپلود به پایان رسید.")
        per_attempt = min(get_per_attempt_timeout(file_path), remaining)

        try:
            return send_with_timeout(file_path, caption, target, per_attempt)
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            transient = any(k in err_str for k in [
                "502", "503", "bad gateway", "timeout", "cannot connect",
                "connection reset", "temporarily unavailable", "error uploading chunk",
            ])
            if transient and attempt < MAX_RETRIES:
                if task:
                    push_status(task, f"⚠️ اتصال ناپایدار، تلاش مجدد ({attempt + 1})...")
                time.sleep(3)
                continue
            break

    raise last_error or RuntimeError("آپلود ناموفق بود.")


# ───────────────────────── دانلود URL ────────────────────────────────────────

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

    cd    = resp.headers.get("content-disposition", "")
    match = re.findall(r'filename="(.+?)"', cd)
    name  = match[0] if match else Path(urlparse(url).path).name
    name  = safe_filename(name or f"file_{int(time.time())}")
    if "." not in name:
        name += ".bin"

    target     = unique_path(URL_DIR / name)
    total      = int(resp.headers.get("content-length") or 0)
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

    archive_path = unique_path(ARCHIVE_DIR / name)
    shutil.copy2(str(target), str(archive_path))
    task["file_name"]    = target.name
    task["file_size"]    = target.stat().st_size
    task["archive_path"] = str(archive_path)
    return target


# ───────────────────────── ZIP رمزدار ────────────────────────────────────────

def make_zip(file_path: Path, password: str) -> Path:
    zip_path = unique_path(file_path.with_suffix(file_path.suffix + ".zip"))
    with pyzipper.AESZipFile(zip_path, "w",
                             compression=pyzipper.ZIP_STORED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode("utf-8"))
        zf.write(file_path, arcname=file_path.name)
    return zip_path


# ───────────────────────── پردازش تسک فایل ───────────────────────────────────

def process_task(task: dict):
    task_type    = task.get("type")
    caption      = task.get("caption", "")
    safe_mode    = task.get("safe_mode", False)
    zip_password = task.get("zip_password", "")
    unique_code  = task.get("unique_code")
    channel_guid = RUBIKA_CHANNEL_GUID or "me"

    if task_type == "local_file":
        local_path = Path(task.get("path", ""))
        if not local_path.exists():
            arch = task.get("archive_path")
            if arch and Path(arch).exists():
                local_path = Path(arch)
            else:
                raise RuntimeError("فایل محلی پیدا نشد.")
    elif task_type == "direct_url":
        local_path = download_url(task)
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

    result = send_with_retry(str(send_path), caption, channel_guid, task)

    rubika_message_id = None
    try:
        if result:
            if hasattr(result, "message_id"):
                rubika_message_id = str(result.message_id)
            elif isinstance(result, dict):
                rubika_message_id = str(
                    result.get("message_id") or
                    result.get("data", {}).get("message_id", "")
                )
    except Exception:
        pass

    if unique_code:
        db.update_rubika_info(unique_code, channel_guid, rubika_message_id or "")

    try:
        if send_path != Path(task.get("archive_path", "")) and send_path.exists():
            send_path.unlink()
    except Exception:
        pass
    try:
        lp = Path(task.get("path", ""))
        if lp.exists() and lp != Path(task.get("archive_path", "")):
            lp.unlink()
    except Exception:
        pass

    push_status(
        task,
        f"✅ **فایل با موفقیت در روبیکا آپلود شد!**\n\n"
        f"🎫 **کد یونیک:** `{unique_code or '—'}`\n\n"
        f"این کد را در ربات روبیکا وارد کن تا فایل برات ارسال بشه."
    )


# ───────────────────────── صف فوروارد ────────────────────────────────────────

def process_forward_queue():
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
            _send_document_sync(
                file_path=archive_path,
                caption=(
                    f"🎫 کد: {fwd['unique_code']}\n"
                    f"📄 {file_record['file_name']}\n"
                    f"📦 {db.pretty_size(file_record['file_size'])}"
                ),
                target=fwd["rubika_user_id"],
            )
            db.complete_forward(fwd["id"])
            db.mark_delivered(fwd["unique_code"])
        except Exception as e:
            db.fail_forward(fwd["id"], str(e))


# ───────────────────── پردازش تسک‌های روبیکا (تلگرام) ────────────────────────

def _run_async(coro):
    """اجرای async در thread جداگانه"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def process_rubika_tasks():
    """پردازش تسک‌های ربات روبیکا: لینک تلگرام، جستجو، getpost"""
    userbot     = tgu.get_userbot()
    bot_ready   = False

    # تلاش برای اتصال یوزربات
    try:
        ready = _run_async(tgu.ensure_userbot())
        bot_ready = ready
    except Exception as e:
        print(f"[rub_worker] یوزربات: {e}")

    while True:
        time.sleep(1)
        task_row = db.pop_rubika_task()
        if not task_row:
            continue

        task_id  = task_row["id"]
        ttype    = task_row["task_type"]
        try:
            data     = json.loads(task_row["task_data"] or "{}")
        except:
            data = {}
        rubika_uid = task_row["rubika_user_id"]
        chat_id  = data.get("chat_id", rubika_uid)

        def send_to_user(text: str):
            try:
                _send_text_sync(text, chat_id)
            except Exception as e:
                print(f"[rub_worker send] {e}")

        def send_file_to_user(path: str, cap: str):
            try:
                _send_document_sync(path, cap, chat_id)
            except Exception as e:
                print(f"[rub_worker file] {e}")

        try:
            if ttype == "join_channel":
                if not bot_ready:
                    send_to_user("❌ قابلیت دسترسی به کانال خصوصی در حال حاضر در دسترس نیست.")
                    db.fail_rubika_task(task_id, "userbot not ready")
                    continue
                title = _run_async(userbot.join_channel(data["hash"]))
                db.save_channel_access(data["hash"])
                send_to_user(
                    f"✅ با موفقیت به کانال پیوستید!\n\n"
                    f"📌 **{title}**\n\n"
                    f"حالا می‌تونی لینک پست‌های این کانال را بفرستی."
                )
                db.complete_rubika_task(task_id)

            elif ttype == "telegram_link":
                if not bot_ready:
                    send_to_user("❌ سرویس دریافت پست‌های تلگرام در حال حاضر در دسترس نیست.")
                    db.fail_rubika_task(task_id, "userbot not ready")
                    continue
                channel = data.get("channel") or int(data.get("channel_id", 0))
                msg_id  = data["msg_id"]
                send_to_user(f"⏳ در حال دریافت پست `{msg_id}` از تلگرام...")

                msg, info = _run_async(userbot.fetch_message(channel, msg_id))
                send_to_user(f"📌 **اطلاعات پست:**\n\n{info}")

                file_path = _run_async(userbot.download_message_media(msg, prefix=f"tg_{msg_id}"))
                if file_path and file_path.exists():
                    cap = f"📨 از تلگرام\n{msg.caption or msg.text or ''}"[:200]
                    send_file_to_user(str(file_path), cap)
                    try:
                        file_path.unlink()
                    except Exception:
                        pass
                else:
                    text_only = msg.text or msg.caption or ""
                    if text_only:
                        send_to_user(f"📝 **متن پست:**\n\n{text_only[:2000]}")
                    else:
                        send_to_user("⚠️ این پست مدیا ندارد یا دانلود ناموفق بود.")
                db.complete_rubika_task(task_id)

            elif ttype == "search":
                if not bot_ready:
                    send_to_user("❌ قابلیت جستجو در حال حاضر در دسترس نیست.")
                    db.fail_rubika_task(task_id, "userbot not ready")
                    continue
                channel = data["channel"]
                query   = data["query"]
                send_to_user(f"🔍 در حال جستجو برای «{query}» در {channel}...")

                msgs = _run_async(userbot.search_channel(channel, query, limit=10))
                if not msgs:
                    send_to_user(f"❌ نتیجه‌ای برای «{query}» در {channel} پیدا نشد.")
                else:
                    result_text = f"🔍 **نتایج جستجو:** «{query}» در {channel}\n\n"
                    for i, m in enumerate(msgs, 1):
                        mtype = tgu.media_type_fa(m)
                        date  = m.date.strftime("%Y-%m-%d") if m.date else "—"
                        views = m.views or 0
                        cap   = (m.caption or m.text or "")[:80]
                        link  = f"https://t.me/{channel.lstrip('@')}/{m.id}"
                        result_text += (
                            f"{i}. {mtype} | 📅 {date} | 👁 {views:,}\n"
                            f"   {cap}\n"
                            f"   🔗 {link}\n\n"
                        )
                    result_text += f"برای دریافت: `/getpost {channel} [شماره پست]`"
                    send_to_user(result_text[:3000])
                db.complete_rubika_task(task_id)

            elif ttype == "getpost":
                if not bot_ready:
                    send_to_user("❌ سرویس دریافت پست در دسترس نیست.")
                    db.fail_rubika_task(task_id, "userbot not ready")
                    continue
                channel = data["channel"]
                msg_id  = data["msg_id"]
                msg, info = _run_async(userbot.fetch_message(channel, msg_id))
                send_to_user(f"📌 **اطلاعات پست #{msg_id}:**\n\n{info}")

                file_path = _run_async(userbot.download_message_media(msg, prefix=f"gp_{msg_id}"))
                if file_path and file_path.exists():
                    send_file_to_user(str(file_path), f"📥 پست #{msg_id} از {channel}")
                    try:
                        file_path.unlink()
                    except Exception:
                        pass
                else:
                    text_only = msg.text or msg.caption or ""
                    if text_only:
                        send_to_user(f"📝 **متن:**\n\n{text_only[:2000]}")
                db.complete_rubika_task(task_id)

            elif ttype == "latest":
                if not bot_ready:
                    send_to_user("❌ سرویس آخرین پست‌ها در دسترس نیست.")
                    db.fail_rubika_task(task_id, "userbot not ready")
                    continue
                channel = data["channel"]
                limit   = data.get("limit", 5)
                send_to_user(f"📬 در حال دریافت {limit} پست آخر از {channel}...")

                msgs = _run_async(userbot.get_latest(channel, limit=limit))
                if not msgs:
                    send_to_user(f"❌ هیچ پستی از {channel} دریافت نشد.")
                else:
                    text = f"📬 **{limit} پست آخر {channel}:**\n\n"
                    for i, m in enumerate(msgs, 1):
                        mtype = tgu.media_type_fa(m)
                        date  = m.date.strftime("%Y-%m-%d %H:%M") if m.date else "—"
                        views = m.views or 0
                        cap   = (m.caption or m.text or "")[:60]
                        link  = f"https://t.me/{channel.lstrip('@')}/{m.id}"
                        text += f"{i}. {mtype} | {date} | 👁 {views:,}\n   {cap}\n   🔗 {link}\n\n"
                    send_to_user(text[:3000])
                db.complete_rubika_task(task_id)

            else:
                db.fail_rubika_task(task_id, f"نوع تسک ناشناخته: {ttype}")

        except Exception as e:
            print(f"[rub_worker task] {ttype} — {e}")
            try:
                send_to_user(f"❌ خطا: {str(e)[:200]}")
            except Exception:
                pass
            db.fail_rubika_task(task_id, str(e))


# ───────────────────────── صف اصلی ───────────────────────────────────────────

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


# ───────────────────────────── اجرا ──────────────────────────────────────────

def worker_loop():
    ensure_session()
    print("✅ ورکر روبیکا شروع به کار کرد.")

    # thread صف فوروارد (کد یونیک → کاربر روبیکا)
    threading.Thread(target=process_forward_queue, daemon=True).start()
    # thread تسک‌های روبیکا (لینک/جستجو)
    threading.Thread(target=process_rubika_tasks,  daemon=True).start()

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