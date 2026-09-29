"""
Where the API keys come from, and a plain explanation when none is found.

Order: environment variables first (handy on servers), then
.streamlit/secrets.toml (local runs). Streamlit Cloud passes its "Secrets"
box to the app as st.secrets, which ui.py reads directly.

Why a separate module? The first real run of the previous version said
"No keys found" although the user HAD created the file: it was saved as
secrets.toml.txt by Notepad. explain_missing_key() now names that mistake
(and the other common ones) instead of leaving the user to guess.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
KEY_NAMES = ("GEMINI_API_KEY", "GROQ_API_KEY", "GEMINI_MODEL", "GROQ_MODEL")
ALIASES = {"GOOGLE_API_KEY": "GEMINI_API_KEY"}          # Google's own docs use this name
PLACEHOLDER_PREFIX = "paste-"


def read_toml(path: Path) -> dict:
    # utf-8-sig: Windows editors sometimes add an invisible BOM at the start of the file
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def load_secrets(path: Path = SECRETS) -> dict:
    found: dict = {}
    if path.exists():
        found.update(read_toml(path))
    for name in KEY_NAMES + tuple(ALIASES):
        if os.environ.get(name):
            found[name] = os.environ[name]
    for alias, real in ALIASES.items():
        if found.get(alias) and not found.get(real):
            found[real] = found[alias]
    return found


def has_real_key(secrets: dict) -> bool:
    g = str(secrets.get("GEMINI_API_KEY", "") or "").strip()
    return bool((g and not g.startswith(PLACEHOLDER_PREFIX)) or secrets.get("GROQ_API_KEY"))


def explain_missing_key(folder: Path = SECRETS.parent) -> list[str]:
    """Human-readable reasons why no key was found, with the fix for each."""
    tips: list[str] = []
    if not folder.exists():
        return [f"The folder {folder.name}/ does not exist here ({folder.parent}).",
                "Fix: run  python setup_key.py  from the project folder."]
    files = sorted(p.name for p in folder.iterdir() if p.is_file())
    tips.append(f"Files in {folder.name}/: {', '.join(files) or '(empty)'}")
    if "secrets.toml" not in files:
        wrong = [f for f in files if f.startswith("secrets") and f != "secrets.toml.example"]
        if wrong:
            tips.append(f"The key file is named '{wrong[0]}' but must be exactly 'secrets.toml' "
                        "(Notepad often adds .txt).")
            tips.append(f'Fix:  mv ".streamlit/{wrong[0]}" .streamlit/secrets.toml   (or run python setup_key.py)')
        else:
            tips.append("There is no secrets.toml. Fix: run  python setup_key.py")
        return tips
    try:
        data = read_toml(folder / "secrets.toml")
    except Exception as err:                     # broken quotes, smart quotes, etc.
        return tips + [f"secrets.toml could not be read: {err}",
                       'It must contain one line like:  GEMINI_API_KEY = "AIza..."  (straight quotes).',
                       "Fix: run  python setup_key.py  to rewrite it."]
    if not data:
        tips.append("secrets.toml is empty. Fix: run  python setup_key.py")
    gkey = str(data.get("GEMINI_API_KEY", "") or "")
    if gkey.startswith(PLACEHOLDER_PREFIX):
        tips.append("GEMINI_API_KEY is still the placeholder 'paste-your-key-here'. Put your real key there.")
    other = [k for k in data if k not in KEY_NAMES and k not in ALIASES]
    if other and not gkey:
        tips.append(f"Found {other} but not GEMINI_API_KEY. The line must start with GEMINI_API_KEY.")
    return tips
