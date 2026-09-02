# /services/openLayer/config.py
import os

# Mapbox
MAPBOX_TOKEN = (
    os.getenv("VECTOPLAN_OPENLAYER_MAPBOX_ACCESS_TOKEN")
    or os.getenv("VECTOPLAN_OPENLAYER_MAPBOX_TOKEN")
    or os.getenv("VECTOPLAN_MAPBOX_TOKEN")
    or os.getenv("MAPBOX_ACCESS_TOKEN")
    or os.getenv("MAPBOX_TOKEN")
    or ""
)

# Startansicht
DEFAULT_LON = float(os.getenv("DEFAULT_LON", "13.405"))  # Berlin
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", "52.52"))
DEFAULT_ZOOM = int(os.getenv("DEFAULT_ZOOM", "17"))

# UI
DISABLE_SCROLL = os.getenv("DISABLE_SCROLL", "0") == "1"

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
