"""
main.py — نقطه اجرای اصلی پروژه Tele2Rub
سه پروسه جداگانه اجرا می‌کنه:
  1. telebot.py  — ربات تلگرام
  2. rub_worker.py — ورکر آپلود روبیکا
  3. rub_bot.py  — ربات روبیکا
"""

import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

procs = {}


def start_proc(name: str, script: str):
    print(f"▶  شروع {name} ...")
    return subprocess.Popen(
        [sys.executable, str(BASE_DIR / script)],
        stdout=None,
        stderr=None,
    )


def main():
    scripts = {
        "ربات تلگرام":    "telebot.py",
        "ورکر روبیکا":    "rub_worker.py",
        "ربات روبیکا":    "rub_bot.py",
    }

    for name, script in scripts.items():
        procs[name] = start_proc(name, script)

    print("✅ همه پروسه‌ها شروع شدند. Ctrl+C برای توقف.\n")

    try:
        while True:
            # بررسی سلامت پروسه‌ها هر ۱۰ ثانیه
            time.sleep(10)
            for name, script in scripts.items():
                proc = procs.get(name)
                if proc and proc.poll() is not None:
                    print(f"⚠️  {name} کرش کرد (کد: {proc.returncode}). راه‌اندازی مجدد...")
                    procs[name] = start_proc(name, script)
    except KeyboardInterrupt:
        print("\n🛑 در حال توقف...")
    finally:
        for name, proc in procs.items():
            if proc and proc.poll() is None:
                proc.terminate()
                print(f"⏹  {name} متوقف شد.")


if __name__ == "__main__":
    main()
