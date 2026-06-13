# services/openLayer/wsgi.py
"""
WSGI-Bridge für Gunicorn.
Exportiert 'application', lädt robust aus services/OpenLayer/app.py.

Reihenfolge:
1) Normal: from app import app as application
2) Fallback: from app import create_app → application = create_app()
3) Harte Fallback-Ladung per Dateipfad (Konflikt 'app' Paket/Modul)
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

application: Any = None

# 1) Standardimport
try:
    import app as app_module  # type: ignore

    if hasattr(app_module, "app"):
        application = getattr(app_module, "app")
    elif hasattr(app_module, "create_app"):
        application = getattr(app_module, "create_app")()
except Exception:
    application = None

# 2) Fallback: Laden per Dateipfad, falls 'app' ein Paket kollidiert
if application is None:
    try:
        root = Path(__file__).resolve().parent
        app_py = root / "app.py"
        if not app_py.exists():
            raise FileNotFoundError(app_py)
        spec = importlib.util.spec_from_file_location("openlayer_app_module", app_py)
        if spec is None or spec.loader is None:
            raise ImportError("cannot create spec for app.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        if hasattr(mod, "app"):
            application = getattr(mod, "app")
        elif hasattr(mod, "create_app"):
            application = getattr(mod, "create_app")()
        else:
            raise AttributeError("app.py missing 'app' or 'create_app'")
    except Exception as exc:
        # Letzter, klarer Fehler für Gunicorn-Logs
        raise RuntimeError(f"WSGI failed to load application: {exc.__class__.__name__}") from exc
