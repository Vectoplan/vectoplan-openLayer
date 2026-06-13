# /services/openLayer/config.py
import os

# Mapbox
MAPBOX_TOKEN = os.getenv(
    "MAPBOX_TOKEN",
    "XXXX",
)

# Startansicht
DEFAULT_LON = float(os.getenv("DEFAULT_LON", "11.576124"))  # München
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", "48.137154"))
DEFAULT_ZOOM = int(os.getenv("DEFAULT_ZOOM", "14"))

# UI
DISABLE_SCROLL = os.getenv("DISABLE_SCROLL", "1") == "1"

# WFS-Proxy-Whitelist (Komma-separiert, ohne Protokoll optional)
WFS_PROXY_WHITELIST = [
    host.strip()
    for host in os.getenv("WFS_PROXY_WHITELIST", "").split(",")
    if host.strip()
]

# Sicherheit
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8090"))
