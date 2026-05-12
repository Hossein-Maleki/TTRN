

import os
import re
import json
import time
import shutil
import threading

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rubpy import Client

import requests
import pyzipper

import db

load_dotenv()


# ─────────────────────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────────────────────

SESSION = os.getenv("RUBIKA_SESSION", "rubika_session").strip()

RUBIKA_CHANNEL_GUID = os.getenv(
    "RUBIKA_CHANNEL_GUID",
    ""
).strip()


# ─────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent

DOWNLOAD_DIR = BASE_DIR / "downloads"
ARCHIVE_DIR = BASE_DIR / "archive"
QUEUE_DIR = BASE_DIR / "queue"

QUEUE_FILE = QUEUE_DIR / "tasks.jsonl"

FAILED_FILE = QUEUE_DIR / "failed.jsonl"

for d in [
    DOWNLOAD_DIR,
    ARCHIVE_DIR,
    QUEUE_DIR,
]:
    d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────
# GLOBAL CLIENT
# ─────────────────────────────────────────────────────────────

app = None


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def safe_filename(name: Optional[str]) -> str:

    name = (name or "file").strip()

    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)

    name = name.rstrip(". ")

    return name[:200] or "file"


def push_failed(task: dict, error: str):

    with open(FAILED_FILE, "a", encoding="utf-8") as f:

        f.write(json.dumps({
            "task": task,
            "error": error,
            "time": time.time(),
        }, ensure_ascii=False) + "\n")


def unique_path(path: Path) -> Path:

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix

    i = 1

    while True:

        candidate = path.with_name(
            f"{stem}_{i}{suffix}"
        )

        if not candidate.exists():
            return candidate

        i += 1


# ─────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────

def connect():

    global app

    if app:
        return app

    print("🔌 اتصال به روبیکا...")

    app = Client(SESSION)

    app.start()

    print("✅ روبیکا متصل شد")

    return app


# ─────────────────────────────────────────────────────────────
# ZIP
# ─────────────────────────────────────────────────────────────

def make_zip(file_path: Path, password: str):

    zip_path = unique_path(
        file_path.with_suffix(
            file_path.suffix + ".zip"
        )
    )

    with pyzipper.AESZipFile(
        zip_path,
        "w",
        compression=pyzipper.ZIP_STORED,
        encryption=pyzipper.WZ_AES
    ) as zf:

        zf.setpassword(
            password.encode("utf-8")
        )

        zf.write(
            file_path,
            arcname=file_path.name
        )

    return zip_path


# ─────────────────────────────────────────────────────────────
# SEND FILE
# ─────────────────────────────────────────────────────────────

def upload_file(
    file_path: str,
    caption: str,
    target_guid: str,
):

    client = connect()

    print(f"📤 Uploading: {file_path}")

    result = client.send_document(
        object_guid=target_guid,
        file=file_path,
        caption=caption or "",
        chunk_size=1024 * 512,
    )

    print("[UPLOAD RESULT]")
    print(result)

    return result


# ─────────────────────────────────────────────────────────────
# TASK
# ─────────────────────────────────────────────────────────────

def process_task(task: dict):

    task_type = task.get("type")

    caption = task.get("caption", "")

    safe_mode = task.get("safe_mode", False)

    zip_password = task.get("zip_password", "")

    unique_code = task.get("unique_code")

    local_path = None


    # ─────────────────────
    # LOCAL FILE
    # ─────────────────────

    if task_type == "local_file":

        local_path = Path(
            task.get("path", "")
        )

        if not local_path.exists():

            raise RuntimeError(
                "فایل پیدا نشد"
            )

    else:

        raise RuntimeError(
            "نوع تسک پشتیبانی نمی‌شود"
        )


    # ─────────────────────
    # ZIP
    # ─────────────────────

    send_path = local_path

    if safe_mode and zip_password:

        print("🔒 Creating ZIP...")

        send_path = make_zip(
            local_path,
            zip_password
        )


    # ─────────────────────
    # UPLOAD TO CHANNEL
    # ─────────────────────

    result = upload_file(
        file_path=str(send_path),
        caption=caption,
        target_guid=RUBIKA_CHANNEL_GUID,
    )


    # ─────────────────────
    # MESSAGE ID
    # ─────────────────────

    message_id = ""

    try:

        if isinstance(result, dict):

            message_id = str(
                result.get("message_id")
                or result.get("data", {}).get("message_id")
                or ""
            )

        elif hasattr(result, "message_id"):

            message_id = str(
                result.message_id
            )

    except Exception:
        pass


    # ─────────────────────
    # SAVE DB
    # ─────────────────────

    if unique_code:

        db.update_rubika_info(
            unique_code,
            RUBIKA_CHANNEL_GUID,
            message_id,
        )

    print(f"✅ Uploaded: {unique_code}")


# ─────────────────────────────────────────────────────────────
# FORWARD QUEUE
# ─────────────────────────────────────────────────────────────

def process_forward_queue():

    while True:

        try:

            item = db.pop_forward()

            if not item:
                time.sleep(1)
                continue

            unique_code = item["unique_code"]

            rubika_user_id = item["rubika_user_id"]

            file_record = db.get_file_by_code(
                unique_code
            )

            if not file_record:

                db.fail_forward(
                    item["id"],
                    "کد پیدا نشد"
                )

                continue

            archive_path = file_record[
                "archive_path"
            ]

            if (
                not archive_path
                or
                not Path(archive_path).exists()
            ):

                db.fail_forward(
                    item["id"],
                    "فایل archive وجود ندارد"
                )

                continue

            print(
                f"📨 Sending to user: {rubika_user_id}"
            )

            upload_file(
                file_path=archive_path,
                caption=(
                    f"🎫 {unique_code}\n"
                    f"📄 {file_record['file_name']}"
                ),
                target_guid=rubika_user_id,
            )

            db.complete_forward(
                item["id"]
            )

            db.mark_delivered(
                unique_code
            )

            print(
                f"✅ Delivered: {unique_code}"
            )

        except Exception as e:

            print(
                f"[FORWARD ERROR] {e}"
            )

            time.sleep(3)


# ─────────────────────────────────────────────────────────────
# QUEUE
# ─────────────────────────────────────────────────────────────

def pop_task():

    if not QUEUE_FILE.exists():
        return None

    with open(
        QUEUE_FILE,
        encoding="utf-8"
    ) as f:

        lines = [
            l for l in f
            if l.strip()
        ]

    if not lines:
        return None

    first = lines[0]

    with open(
        QUEUE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.writelines(lines[1:])

    return json.loads(first)


# ─────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────

def worker_loop():

    connect()

    print("✅ Worker Started")

    threading.Thread(
        target=process_forward_queue,
        daemon=True
    ).start()

    while True:

        try:

            task = pop_task()

            if not task:
                time.sleep(1)
                continue

            print("[NEW TASK]")
            print(json.dumps(
                task,
                ensure_ascii=False,
                indent=2
            ))

            process_task(task)

        except Exception as e:

            print(f"[WORKER ERROR] {e}")

            try:
                push_failed(task, str(e))
            except Exception:
                pass

            time.sleep(3)


# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    worker_loop()