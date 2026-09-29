"""
Create .streamlit/secrets.toml with your Gemini key, correctly, in one step.

    python setup_key.py

Why this script exists: creating the file by hand on Windows goes wrong
easily (Notepad saves "secrets.toml.txt", curly quotes, an invisible BOM).
This writes the exact file the app expects, then checks that Git ignores it.
Your key is typed here, stays on your computer, and is never printed.
Get a key at https://aistudio.google.com/apikey
"""
from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
FOLDER = ROOT / ".streamlit"
TARGET = FOLDER / "secrets.toml"


def ask_key() -> str:
    prompt = "Paste your Gemini API key and press Enter: "
    try:
        # Hidden input in normal terminals. Git Bash (mintty) has no real TTY, so use input() there.
        key = getpass.getpass(prompt) if sys.stdin.isatty() else input(prompt)
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nCancelled. Nothing was written.")
    return key.strip().strip('"').strip("'")


def main() -> None:
    key = ask_key()
    if not key or key.startswith("paste-"):
        sys.exit("No key entered. Nothing was written.")
    if " " in key or len(key) < 20:
        sys.exit("That does not look like an API key (too short or has spaces). Nothing was written.")
    if not key.startswith("AIza"):
        print("Note: Gemini keys usually start with 'AIza'. Saving anyway.")

    FOLDER.mkdir(exist_ok=True)
    for stray in FOLDER.glob("secrets.toml.*"):          # e.g. secrets.toml.txt from Notepad
        if stray.name != "secrets.toml.example":
            stray.unlink()
            print(f"Removed the misnamed file {stray.name}")
    TARGET.write_text(f'GEMINI_API_KEY = "{key}"\n', encoding="utf-8", newline="\n")
    print(f"Saved {TARGET.relative_to(ROOT)} (key ...{key[-4:]})")

    try:
        ok = subprocess.run(["git", "check-ignore", "-q", str(TARGET)], cwd=ROOT).returncode == 0
        print("Git ignores this file: it will not be uploaded to GitHub." if ok
              else "WARNING: Git does NOT ignore this file. Do not commit it; check .gitignore.")
    except FileNotFoundError:
        pass
    print("Next:  python -m feedback.llm")


if __name__ == "__main__":
    main()
