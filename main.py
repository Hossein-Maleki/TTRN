"""
main.py — نقطه اجرای اصلی Tele2Rub v2.2
اجرای سه پروسه جداگانه:
  1. telebot.py  — ربات تلگرام
  2. rub_worker.py — ورکر روبیکا
  3. rub_bot.py  — ربات روبیکا
"""

import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

procs = {}

def start_proc(name: str, script: str):
    """شروع یک پروسه"""
    print(f"▶  شروع {name} ...")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc
    except Exception as e:
        print(f"❌ خطا در شروع {name}: {e}")
        return None

def main():
    scripts = {
        "ربات تلگرام": "telebot.py",
        "ورکر روبیکا": "rub_worker.py",
        "ربات روبیکا": "rub_bot.py",
    }

    for name, script in scripts.items():
        procs[name] = start_proc(name, script)

    print("✅ تمام پروسه‌ها شروع شدند.\n")
    print("🟢 سیستم در حال اجراست. Ctrl+C برای توقف.\n")

    try:
        while True:
            time.sleep(10)
            
            for name, script in scripts.items():
                proc = procs.get(name)
                if proc and proc.poll() is not None:
                    print(f"⚠️  {name} کرش کرد. راه‌اندازی مجدد...")
                    procs[name] = start_proc(name, script)
                    time.sleep(2)

    except KeyboardInterrupt:
        print("\n\n🛑 در حال متوقف کردن تمام پروسه‌ها...")
    finally:
        for name, proc in procs.items():
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                    print(f"⏹  {name} متوقف شد.")
                except Exception as e:
                    print(f"❌ خطا در متوقف کردن {name}: {e}")
                    try:
                        proc.kill()
                    except Exception:
                        pass

if __name__ == "__main__":
    print("╔════════════════════════════════════════════╗")
    print("║         🚀 Tele2Rub v2.2                   ║")
    print("║    انتقال فایل تلگرام → روبیکا              ║")
    print("╚════════════════════════════════════════════╝\n")
    main()
