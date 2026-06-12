"""Shared Jinja2 templates env, resolved package-relative so the app works when
installed (pip) or run from any working directory — not just the repo root."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

_PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _PACKAGE_DIR / "templates"
STATIC_DIR = _PACKAGE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
