"""
EMERGENCY BRAKE MONITOR  ·  versión definitiva (un solo archivo)
=====================================================================
Detecta trenes detenidos en vía, frenadas bruscas y riesgo de alcance, y avisa con
sirena continua (hasta reconocerla), notificaciones del navegador, Telegram, ntfy y webhook.

    pip install streamlit streamlit-folium streamlit-autorefresh folium pandas numpy requests
    streamlit run emergency_brake_monitor.py

Variables de entorno / st.secrets (opcionales):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NTFY_TOPIC, NTFY_SERVER,
    ALERT_WEBHOOK_URL, ADIF_INCIDENTS_URL (JSON con avisos de Adif), EBM_DB, CARTO_API_KEY
"""
import html
import inspect
import io
import json
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from folium.plugins import MarkerCluster
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:  # noqa: BLE001 - sin tzdata (Windows) se usa la hora local
    TZ = None

# ==========================================
# 1. Página y estilo "cabina"
# ==========================================
st.set_page_config(layout="wide", page_title="Emergency Brake Monitor", page_icon="🚆")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=B612+Mono:wght@400;700&family=B612:wght@400;700&display=swap');
html, body, .stApp, [class*="css"] { font-family: 'B612', 'Segoe UI', system-ui, sans-serif; }
.stApp { background: radial-gradient(1200px 600px at 50% -10%, #101a26 0%, #05080c 60%); color: #e7edf2; }
.block-container { padding: .8rem 1.4rem !important; max-width: 100% !important; }
#MainMenu, footer, header { visibility: hidden; }
.mono { font-family: 'B612 Mono', ui-monospace, Consolas, monospace; }

/* Barra superior */
.cp-bar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:8px 14px;
  background:#070c12; border:1px solid #1f2a36; border-radius:6px; margin-bottom:8px; }
.cp-title { font-weight:700; font-size:20px; letter-spacing:.06em; color:#e7edf2; }
.cp-title small { color:#35d0ff; font-weight:400; margin-left:10px; font-size:12px; letter-spacing:.12em; }
.cp-clock { font-family:'B612 Mono',monospace; color:#39ff88; font-size:20px; text-shadow:0 0 8px rgba(57,255,136,.45); }
.cp-sub { color:#7d8da0; font-size:11px; letter-spacing:.04em; }

/* Anunciadores */
.ann-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(112px,1fr)); gap:6px; margin-bottom:8px; }
.ann { background:#0a0f15; border:1px solid #1f2a36; border-radius:4px; padding:6px 9px; font-size:10.5px;
  letter-spacing:.08em; color:#5b6b7a; text-transform:uppercase; }
.ann .lamp { width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:7px; background:#26313c; }
.ann i { display:block; font-style:normal; font-family:'B612 Mono',monospace; font-size:17px; color:#e7edf2;
  font-weight:700; margin-top:3px; letter-spacing:0; }
.ann.ok { color:#a9f1c6; } .ann.ok .lamp { background:#39ff88; box-shadow:0 0 8px #39ff88; }
.ann.caution { color:#ffd27a; border-color:#5c4410; } .ann.caution .lamp { background:#ffb000; box-shadow:0 0 8px #ffb000; }
.ann.caution i { color:#ffb000; }
.ann.warn { color:#ffb3b3; border-color:#7a1f1f; background:#1a0a0a; animation:blink .9s steps(2) infinite; }
.ann.warn .lamp { background:#ff2d2d; box-shadow:0 0 10px #ff2d2d; } .ann.warn i { color:#ff5a5a; }
@keyframes blink { 50% { background:#2b0d0d; } }

/* Master warning */
.master { background:rgba(255,45,45,.14); border:2px solid #ff2d2d; border-radius:6px; padding:12px 16px;
  color:#ffd0d0; margin:6px 0 8px; animation:pulse 1s infinite; }
.master h4 { margin:0 0 6px; color:#ff6b6b; letter-spacing:.14em; font-size:15px; }
.master div { margin-bottom:3px; font-size:13px; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(255,45,45,.7);} 70%{box-shadow:0 0 0 16px rgba(255,45,45,0);} 100%{box-shadow:0 0 0 0 rgba(255,45,45,0);} }
button[kind="primary"] { background:#ff2d2d !important; border:0 !important; color:#fff !important; font-weight:700 !important;
  letter-spacing:.08em; min-height:46px; }

/* Indicadores */
.gauges { display:flex; gap:8px; margin:4px 0 8px; }
.gauge { flex:1; background:#070c12; border:1px solid #1f2a36; border-radius:6px; padding:8px 10px; text-align:center; }
.gauge b { display:block; font-family:'B612 Mono',monospace; font-size:24px; color:#35d0ff; }
.gauge span { font-size:10px; color:#7d8da0; text-transform:uppercase; letter-spacing:.1em; }

/* EICAS: mensajes por prioridad */
.eicas { background:#05090d; border:1px solid #1f2a36; border-radius:6px; padding:8px; }
.msg { font-family:'B612 Mono',monospace; font-size:12px; padding:6px 8px; margin-bottom:5px; border-left:4px solid #555;
  background:#0a1017; border-radius:3px; color:#dbe4ec; }
.msg b { display:block; font-size:11px; letter-spacing:.1em; margin-bottom:2px; }
.msg.risk { border-color:#ff0000; } .msg.risk b { color:#ff5a5a; }
.msg.stopped { border-color:#ff3232; } .msg.stopped b { color:#ff6b6b; }
.msg.brake { border-color:#e67e22; } .msg.brake b { color:#f39c4a; }
.msg.early { border-color:#f1c40f; } .msg.early b { color:#f1c40f; }
.msg.system { border-color:#8b949e; } .msg.system b { color:#aab4be; }
.nominal { color:#39ff88; font-family:'B612 Mono',monospace; font-size:12px; padding:8px; }

/* Llegadas con retraso */
.arr { display:grid; grid-template-columns:64px 1fr auto; gap:10px; align-items:center; background:#0a1017;
  border-radius:3px; padding:7px 10px 7px 0; margin-bottom:5px; }
.arr .min { font-family:'B612 Mono',monospace; font-weight:700; font-size:19px; text-align:center; border-right:4px solid; }
.arr.grave .min { color:#f4603f; border-color:#f4603f; } .arr.leve .min { color:#f0b429; border-color:#f0b429; }
.arr .t { font-weight:700; font-size:12.5px; } .arr .t small { font-weight:400; color:#7d8da0; margin-left:6px; font-family:'B612 Mono',monospace; }
.arr .d { color:#7d8da0; font-size:11px; margin-top:2px; } .arr .h { font-family:'B612 Mono',monospace; font-size:13px; text-align:right; color:#cfe0ee; }

/* Ficha */
.ficha { background:#0F171F; border-left:4px solid #35d0ff; padding:12px 14px; border-radius:4px; font-size:13px; }
.ficha h3 { margin:0 0 2px; font-size:16px; } .ficha .r { color:#7d8da0; margin-bottom:8px; }
.ficha dl { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; margin:0; }
.ficha dt { color:#7d8da0; } .ficha dd { margin:0; text-align:right; font-family:'B612 Mono',monospace; }
.leg { display:flex; gap:14px; flex-wrap:wrap; font-size:11px; color:#7d8da0; margin:2px 0 6px; }
.leg span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:-1px; background:var(--c); }
.inc { border-left:4px solid #7fa7d6; background:#0a1017; padding:8px 10px; margin-bottom:6px; border-radius:3px; font-size:12.5px; }
.inc.grave { border-color:#f4603f; } .inc.leve { border-color:#f0b429; } .inc b { display:block; margin-bottom:2px; }
.riskbox { display:flex; align-items:center; gap:14px; background:#05090d; border:1px solid #1f2a36; border-radius:6px; padding:10px 14px; margin-bottom:8px; }
.riskbox b { font-family:'B612 Mono',monospace; font-size:38px; line-height:1; }
.riskbox span { font-size:12px; letter-spacing:.14em; color:#9fb0c0; }
.riskbox.low b { color:#39ff88; } .riskbox.mid b { color:#f1c40f; } .riskbox.high b { color:#ff9f1a; }
.riskbox.crit b { color:#ff3232; animation:blinkt .9s steps(2) infinite; }
@keyframes blinkt { 50% { opacity:.35; } }
.rrow { display:grid; grid-template-columns:1fr 80px 30px; gap:8px; align-items:center; font-size:11.5px; margin-bottom:7px; }
.rrow small { display:block; color:#7d8da0; font-size:10px; }
.rrow .bar { height:8px; background:#121b25; border-radius:4px; overflow:hidden; } .rrow .bar i { display:block; height:100%; }
.rrow em { font-family:'B612 Mono',monospace; font-style:normal; text-align:right; }
.cutrow { border-left:4px solid #ff2d2d; background:#12090b; padding:8px 10px; margin-bottom:6px; border-radius:3px; font-size:12.5px; }
.cutrow small { color:#8a98a8; display:block; }
.arr .h del { display:block; color:#7d8da0; font-size:11px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. Constantes y utilidades
# ==========================================
URL_FLOTA = "https://tiempo-real.largorecorrido.renfe.com/renfe-visor/flotaLD.json"
URL_ESTACIONES = "https://tiempo-real.largorecorrido.renfe.com/renfe-visor/estaciones.geojson"
URL_RUTAS = "https://tiempo-real.largorecorrido.renfe.com/renfe-visor/trenesConEstacionesLD.json"

# Código de producto de Renfe (tabla contrastada con el visor público)
NOM_PROD = {2: "AVE", 25: "AVE", 28: "Avlo", 3: "Avant", 11: "Alvia", 10: "Euromed", 13: "Intercity",
            4: "Talgo", 5: "Altaria", 7: "Diurno", 8: "Estrella", 9: "Tren Hotel", 24: "AV City",
            14: "Andalucía Exprés", 15: "Catalunya Exprés", 16: "Media Distancia", 18: "Regional",
            19: "Regional Exprés", 20: "TRD"}
GRUPOS = {"AVE": [2, 25], "Avlo": [28], "Avant": [3], "Alvia": [11],
          "Euromed e Intercity": [10, 13, 4, 5, 7, 8, 9, 24],
          "Media distancia y regionales": [14, 15, 16, 18, 19, 20]}

CORTOS = {"60000": "Madrid Atocha", "17000": "Madrid Chamartín", "18000": "Madrid Atocha",
          "10000": "Madrid Príncipe Pío", "71801": "Barcelona Sants", "79400": "Barcelona França",
          "03216": "València J. Sorolla", "65000": "València Nord", "51003": "Sevilla", "60911": "Alicante",
          "04040": "Zaragoza", "08223": "Vigo", "31412": "A Coruña", "15100": "León", "15211": "Oviedo",
          "11511": "San Sebastián", "04307": "Figueres", "87089": "Marsella", "87303": "Lyon",
          "03309": "Villena AV", "08240": "Medina AV", "60600": "Albacete", "03208": "Cuenca",
          "04007": "Guadalajara", "08004": "Segovia", "04104": "Camp de Tarragona", "50500": "Córdoba",
          "54413": "Málaga"}

# (nombre, provincias, caja lat/lon de respaldo si la estación no trae provincia)
ZONAS = [
    ("Toda España", None, None),
    ("Madrid", ["MADRID"], (39.8, 41.2, -4.6, -3.0)),
    ("Cataluña", ["BARCELONA", "GIRONA", "GERONA", "LLEIDA", "LERIDA", "TARRAGONA"], (40.5, 42.9, 0.1, 3.4)),
    ("C. Valenciana", ["VALENCIA", "ALICANTE", "CASTELLON"], (37.8, 40.8, -1.6, 0.7)),
    ("Andalucía", ["SEVILLA", "MALAGA", "CORDOBA", "GRANADA", "CADIZ", "HUELVA", "JAEN", "ALMERIA"], (36.0, 38.8, -7.6, -1.6)),
    ("Galicia", ["CORUNA", "A CORUNA", "LUGO", "OURENSE", "ORENSE", "PONTEVEDRA"], (41.8, 43.9, -9.4, -6.7)),
    ("Norte", ["ASTURIAS", "CANTABRIA", "VIZCAYA", "BIZKAIA", "GUIPUZCOA", "GIPUZKOA", "ALAVA", "ARABA",
               "NAVARRA", "LEON", "BURGOS", "PALENCIA", "LA RIOJA", "RIOJA"], (42.0, 43.8, -8.0, -0.7)),
]

MONITOR_VERSION = "v5"       # Cambiarlo fuerza a Streamlit a crear un monitor nuevo
DEFAULT_REFRESH_S = 15
DEFAULT_POLL_S = 10
SLOW_KMH = 5
MIN_MOVE_M = 10
SPEED_SMOOTH = 0.6
GLITCH_KMH = 450
MAX_GAP_S = 120
FROZEN_AFTER_S = 90
RETENTION_DAYS = 30           # memoria de incidentes y tramos (SQLite)
MASS_LIMIT = 6

DEFAULT_CFG = {
    "early_stop_s": 30, "min_stop_s": 60, "station_radius_m": 1000,
    "risk_dist_m": 5000, "risk_ttc_s": 120, "risk_heading_deg": 60, "risk_min_kmh": 30,
    "risk_include_suspect": True,
    "brake_min_kmh": 80, "brake_ms2": 0.9, "brake_station_m": 3000, "brake_hold_s": 120,
    "push_min_rank": 1,
    "accident_s": 240,          # detenido tanto tiempo lejos de estación => posible accidente
    "cut_half_km": 5,           # semilongitud (km) del tramo cortado automático alrededor del tren
    "gps_stale_s": 600,         # señal GPS más antigua que esto => tren "sin señal": no genera alarmas
    "cut_warn_m": 10000,        # distancia a la que un tren que se acerca a un tramo cortado genera aviso
}

LEVELS = {
    "early":    {"label": "AVISO TEMPRANO",    "icon": "🟡", "color": "#f1c40f", "rank": 1, "beeps": 2, "repeat_s": 180},
    "brake":    {"label": "FRENADA BRUSCA",    "icon": "🟠", "color": "#e67e22", "rank": 2, "beeps": 3, "repeat_s": 300},
    "stopped":  {"label": "DETENIDO EN VÍA",   "icon": "🔴", "color": "#ff3232", "rank": 3, "beeps": 4, "repeat_s": 120},
    "accident": {"label": "POSIBLE ACCIDENTE",  "icon": "💥", "color": "#ff0000", "rank": 5, "beeps": 10, "repeat_s": 60},
    "risk":     {"label": "RIESGO CRÍTICO",    "icon": "🚨", "color": "#ff0000", "rank": 4, "beeps": 8, "repeat_s": 30},
    "system":   {"label": "AVISO DEL SISTEMA", "icon": "⚠", "color": "#8b949e", "rank": 0, "beeps": 1, "repeat_s": 900},
    "resolved": {"label": "RESUELTO",          "icon": "✅", "color": "#2ecc71", "rank": 0, "beeps": 0, "repeat_s": 10 ** 9},
}

BASE_COLUMNS = [
    "cod_comercial", "tipo", "grupo", "cod_prod", "lat", "lon", "retraso_min", "speed_kmh", "inst_kmh",
    "prev_inst_kmh", "decel_ms2", "gps_age_s", "heading", "has_heading", "stopped_for_s", "dist_to_station",
    "est_ant", "est_sig", "origen", "destino", "hora_sig", "mat", "accesible",
]
RULE_COLUMNS = ["is_stopped", "is_suspect", "braking"]

DB_PATH = os.getenv("EBM_DB") or os.getenv("RENFE_DB") or "emergency_brake.db"
DB_LOCK = threading.Lock()


def esc(value):
    """Escapa cualquier dato externo antes de meterlo en HTML."""
    return html.escape(str(value if value is not None else ""))


def to_float(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def ascii_safe(text):
    norm = unicodedata.normalize("NFKD", str(text))
    return norm.encode("ascii", "ignore").decode("ascii")


def norm_text(s):
    n = unicodedata.normalize("NFD", str(s or "").upper())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalpha() or c == " " else " " for c in n).split())


def norm_code(v):
    if v is None:
        return ""
    s = str(v).strip()
    return s.zfill(5) if s.isdigit() else s


def pick(d, keys):
    """Primer valor no vacío de d cuyas claves coincidan (sin distinguir mayúsculas) con keys."""
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_heading(lat1, lon1, lat2, lon2):
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def nearest_station_m(lat, lon, stations_arr):
    if stations_arr is None or len(stations_arr) == 0:
        return None
    phi1 = math.radians(lat)
    phi2 = np.radians(stations_arr[:, 0])
    dphi = phi2 - phi1
    dlam = np.radians(stations_arr[:, 1] - lon)
    a = np.sin(dphi / 2) ** 2 + math.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    d = 2 * 6371000 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return float(d.min())


def grupo_de(code):
    for name, codes in GRUPOS.items():
        if code in codes:
            return name
    return "Otros"


def fmt_delay(m):
    m = int(m)
    if m < 0:
        return f"{-m} min adelantado"
    if m == 0:
        return "En hora"
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


def fmt_m(value):
    v = to_float(value)
    return "?" if v is None else str(int(round(v)))


def fmt_clock(ts, fmt="%H:%M:%S"):
    return datetime.fromtimestamp(ts, TZ).strftime(fmt)


def label_est(code, info):
    """Nombre corto de estación a partir de su código."""
    code = norm_code(code)
    if not code:
        return "?"
    if code in CORTOS:
        return CORTOS[code]
    n = (info.get(code) or {}).get("n")
    if n:
        n = str(n).split("/")[0].replace(" - ", " ").strip()
        return n if len(n) <= 28 else n[:27] + "…"
    return f"estación {code}"


def in_zone(zone, code, info):
    for name, provs, box in ZONAS:
        if name != zone:
            continue
        if provs is None:
            return True
        e = info.get(norm_code(code))
        if not e:
            return False
        p = norm_text(e.get("prov"))
        if p:
            return any(p == x or p.endswith(" " + x) or p.startswith(x + " ") for x in provs)
        return bool(box) and box[0] <= e["lat"] <= box[1] and box[2] <= e["lon"] <= box[3]
    return True


def seg_nearest(lat, lon, a, b):
    """Punto más cercano a (lat, lon) sobre el segmento a-b y distancia en metros (proyección local)."""
    k = math.cos(math.radians(lat))

    def xy(p):
        return ((p[1] - lon) * k * 111320.0, (p[0] - lat) * 110540.0)

    ax, ay = xy(a)
    bx, by = xy(b)
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / l2))
    px, py = ax + t * dx, ay + t * dy
    return (lat + py / 110540.0, lon + px / (111320.0 * max(k, 1e-6))), math.hypot(px, py)


def path_nearest(lat, lon, pts):
    """Punto más cercano de una polilínea y distancia (m)."""
    best = (None, float("inf"))
    for i in range(len(pts) - 1):
        p, d = seg_nearest(lat, lon, pts[i], pts[i + 1])
        if d < best[1]:
            best = (p, d)
    return best


def offset_point(lat, lon, bearing, dist_m):
    h = math.radians(bearing)
    return (lat + dist_m * math.cos(h) / 110540.0,
            lon + dist_m * math.sin(h) / (111320.0 * max(math.cos(math.radians(lat)), 1e-6)))


def parse_iso_ts(v):
    try:
        d = datetime.fromisoformat(str(v))
        if d.tzinfo is None and TZ is not None:
            d = d.replace(tzinfo=TZ)  # fechaActualizacion viene en hora de Madrid
        return d.timestamp()
    except (ValueError, TypeError):
        return None


def parse_latlon_list(text):
    """'40.1,-3.7; 38.0,-4.5' -> [(40.1,-3.7),(38.0,-4.5)]"""
    pts = []
    for chunk in str(text or "").replace("\n", ";").split(";"):
        parts = chunk.replace(" ", "").split(",")
        if len(parts) == 2:
            la, lo = to_float(parts[0]), to_float(parts[1])
            if la is not None and lo is not None:
                pts.append((la, lo))
    return pts


def parse_tramo(v):
    """Geometría de un aviso de Adif: lista de [lat, lon] o dict {a:[..], b:[..]}."""
    try:
        if isinstance(v, dict):
            v = [v.get("a"), v.get("b")]
        pts = [(float(p[0]), float(p[1])) for p in (v or [])]
        return pts if len(pts) >= 2 else []
    except (TypeError, ValueError, IndexError):
        return []


def sparkline(values, w=230, h=46, color="#35d0ff"):
    if len(values) < 2:
        return ""
    vmax = max(max(values), 10.0)
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - 3 - (v / vmax) * (h - 6):.1f}" for i, v in enumerate(values))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="background:#070c12;border-radius:3px">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/></svg>')


def stretch_kwargs(func):
    """Compatibilidad entre versiones de Streamlit (use_container_width vs width='stretch')."""
    try:
        if "width" in inspect.signature(func).parameters:
            return {"width": "stretch"}
    except (TypeError, ValueError):
        pass
    return {"use_container_width": True}


def render_html(code, height=0):
    """Inyecta HTML/JS en un iframe (st.iframe si existe, si no components.html). Nunca falla en silencio."""
    last_err = None
    new_api = getattr(st, "iframe", None)
    if new_api is not None:
        for h in dict.fromkeys([height, max(height, 1)]):
            try:
                new_api(code, height=h)
                st.session_state.pop("render_html_error", None)
                return True
            except Exception as e:  # noqa: BLE001
                last_err = e
    try:
        components.html(code, height=height)
        st.session_state.pop("render_html_error", None)
        return True
    except Exception as e:  # noqa: BLE001
        last_err = e
    st.session_state["render_html_error"] = type(last_err).__name__ if last_err else "desconocido"
    return False


# ==========================================
# 3. Conexión a datos
# ==========================================
@st.cache_resource
def get_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s


STATIONS_CACHE = os.getenv("EBM_STATIONS_CACHE", "ebm_stations.json")


def parse_stations(data):
    """Lista de dicts {code, n, prov, lat, lon}. Acepta Point/MultiPoint o lat/lon dentro de las propiedades."""
    out = []
    for f in (data or {}).get("features", []):
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        lat = lon = None
        c = geom.get("coordinates") or []
        if geom.get("type") == "MultiPoint" and c:
            c = c[0]
        if geom.get("type") in ("Point", "MultiPoint") and len(c) >= 2:
            lon, lat = to_float(c[0]), to_float(c[1])
        if lat is None or lon is None:
            lat, lon = to_float(pick(props, ["latitud", "lat", "latitude"])), to_float(pick(props, ["longitud", "lon", "lng", "longitude"]))
        if lat is None or lon is None:
            continue
        code = pick(props, ["codigo", "cod_estacion", "codEstacion", "codigoEstacion", "cdgoUIC", "id"]) or f.get("id")
        name = pick(props, ["nombre", "name", "nombreEstacion", "descripcion", "desc", "estacion"])
        prov = pick(props, ["provincia", "province"])
        out.append({"code": norm_code(code), "n": name or "", "prov": prov or "", "lat": lat, "lon": lon})
    return out


def parse_stations_csv(text):
    """CSV con cabecera: lat, lon y opcionalmente codigo, nombre, provincia."""
    import csv
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        lat, lon = to_float(pick(r, ["lat", "latitud", "latitude"])), to_float(pick(r, ["lon", "lng", "longitud", "longitude"]))
        if lat is None or lon is None:
            continue
        out.append({"code": norm_code(pick(r, ["codigo", "code", "cod"])), "n": pick(r, ["nombre", "name"]) or "",
                    "prov": pick(r, ["provincia", "prov"]) or "", "lat": lat, "lon": lon})
    return out


def save_stations_cache(stations):
    try:
        with open(STATIONS_CACHE, "w", encoding="utf-8") as f:
            json.dump(stations, f)
    except OSError:
        pass


def load_stations_cache():
    try:
        with open(STATIONS_CACHE, encoding="utf-8") as f:
            return [x for x in json.load(f) if isinstance(x, dict) and "lat" in x and "lon" in x]
    except (OSError, ValueError, TypeError):
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stations():
    r = get_session().get(URL_ESTACIONES, timeout=10)  # si falla lanza: no se cachea vacío
    r.raise_for_status()
    return parse_stations(r.json())


def load_stations():
    try:
        stations = fetch_stations()
        if stations:
            st.session_state.last_stations = stations
            return stations
    except (requests.RequestException, ValueError):
        pass
    return st.session_state.get("last_stations", [])


@st.cache_data(ttl=5, show_spinner=False)
def fetch_data():
    r = get_session().get(URL_FLOTA, params={"v": int(time.time() * 1000)}, timeout=10)
    r.raise_for_status()
    return r.json(), time.time()


def load_feed():
    try:
        raw, ts = fetch_data()
        if isinstance(raw, dict) and "trenes" in raw:
            st.session_state.last_feed = (raw, ts)
            return raw, ts, False
    except (requests.RequestException, ValueError):
        pass
    last = st.session_state.get("last_feed")
    return (last[0], last[1], True) if last else (None, None, True)


def parse_incidents(data):
    """Normaliza avisos de Adif de un JSON (lista, o dict con lista en incidencias/avisos/items/data)."""
    items = data
    if isinstance(data, dict):
        items = next((data[k] for k in ("incidencias", "avisos", "items", "data", "results")
                      if isinstance(data.get(k), list)), [])
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        title = pick(it, ["titulo", "title", "nombre", "asunto"]) or "Aviso"
        text = pick(it, ["texto", "descripcion", "description", "detalle", "text", "mensaje"]) or ""
        if isinstance(text, list):
            text = " ".join(str(x) for x in text)
        scope = pick(it, ["ambito", "zona", "linea", "tramo"]) or ""
        blob = norm_text(f"{title} {text}")
        nivel = "grave" if any(k in blob for k in ("SUSPEND", "INTERRUMP", "CORTE", "CORTADA", "ACCIDENTE")) \
            else "leve" if any(k in blob for k in ("RETRASO", "LIMITACION", "AFECTA", "INCIDENCIA")) else "info"
        out.append({"titulo": str(title), "texto": str(text), "ambito": str(scope), "nivel": nivel,
                    "pts": parse_tramo(pick(it, ["tramo", "puntos", "geometry"]))})
    return out


_STOP_KEYS = ["estaciones", "paradas", "stops", "recorrido", "ruta", "listaEstaciones", "itinerario"]
_CODE_KEYS = ["codEstacion", "codigoEstacion", "codEst", "codigo", "cod", "estacion", "id", "stationCode"]
_TIME_KEYS = ["horaLlegada", "horaLlegadaPlanificada", "horaProgramada", "horaPrevista", "horaPaso", "hora",
              "llegada", "horaSalida", "salida", "horaEstimada", "time"]


def _hhmm(v):
    """'2026-10-31T21:40:00' o '21:40' -> '21:40' ('' si no es una hora)."""
    v = str(v or "")
    if "T" in v and len(v) >= 16:
        return v[11:16]
    return v[:5] if len(v) >= 5 and v[2] == ":" else ""


def add_minutes_hhmm(hhmm, minutes):
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        return hhmm
    t = (h * 60 + m + int(minutes)) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


def parse_routes(data):
    """
    {codComercial: [{'code','time'}...]} a partir de trenesConEstacionesLD.json. Lector TOLERANTE: no conozco el
    esquema exacto, así que busca la lista de paradas y los campos de código y hora por nombres habituales.
    """
    items = data
    if isinstance(data, dict):
        items = next((data[k] for k in ("trenes", "trains", "data", "items", "results") if isinstance(data.get(k), list)), None)
        if items is None:
            items = [dict(v, codComercial=k) for k, v in data.items() if isinstance(v, dict)]
    out = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        cod = str(pick(it, ["codComercial", "cod_comercial", "numeroTren", "tren", "numero"]) or "")
        if not cod:
            continue
        raw_stops = next((pick(it, [k]) for k in _STOP_KEYS if isinstance(pick(it, [k]), list)), None)
        if raw_stops is None:
            raw_stops = next((v for v in it.values() if isinstance(v, list) and len(v) >= 2 and isinstance(v[0], dict)), None)
        stops = []
        for sp in raw_stops or []:
            if isinstance(sp, dict):
                code, tm = norm_code(pick(sp, _CODE_KEYS)), ""
                for k in _TIME_KEYS:
                    tm = _hhmm(pick(sp, [k]))
                    if tm:
                        break
            elif isinstance(sp, (list, tuple)) and sp:
                code = norm_code(sp[0])
                tm = _hhmm(sp[1]) if len(sp) > 1 else ""
            else:
                continue
            if code or tm:
                stops.append({"code": code, "time": tm})
        if stops:
            out[cod] = stops
    return out


def routes_debug(data, routes):
    items = data.get("trenes") if isinstance(data, dict) and isinstance(data.get("trenes"), list) else \
        (data if isinstance(data, list) else [])
    first = items[0] if items and isinstance(items[0], dict) else (data if isinstance(data, dict) else {})
    return {"registros": len(items), "con_paradas": len(routes), "campos": list(first.keys())[:25]}


def planned_arrival(routes, cod, dest_code=""):
    """Hora prevista de llegada al destino final (hh:mm) o ''."""
    stops = routes.get(str(cod)) or []
    for sp in reversed(stops):
        if sp["time"] and (not dest_code or sp["code"] == dest_code):
            return sp["time"]
    return next((sp["time"] for sp in reversed(stops) if sp["time"]), "")


# ==========================================
# 4. Registro persistente (SQLite)
# ==========================================
INC_COLUMNS = ["id", "kind", "ref", "first_ts", "last_ts", "resolved_ts", "lat", "lon", "msg", "severity", "confirmed"]


def _db_run(sql, params=()):
    try:
        with DB_LOCK, closing(sqlite3.connect(DB_PATH, timeout=5)) as con:
            cur = con.execute(sql, params)
            con.commit()
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount
    except (sqlite3.Error, OSError):
        return None


def _db_query(sql, params=()):
    try:
        with DB_LOCK, closing(sqlite3.connect(DB_PATH, timeout=5)) as con:
            return pd.read_sql_query(sql, con, params=params)
    except (sqlite3.Error, OSError, pd.errors.DatabaseError):
        return pd.DataFrame()


def db_init():
    try:
        with DB_LOCK, closing(sqlite3.connect(DB_PATH, timeout=5)) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS eventos ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, hora TEXT, nivel TEXT, "
                "fase TEXT, clave TEXT, mensaje TEXT, lat REAL, lon REAL)")
            con.execute(
                "CREATE TABLE IF NOT EXISTS incidentes ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT, first_ts REAL, last_ts REAL, "
                "resolved_ts REAL, lat REAL, lon REAL, msg TEXT, severity INTEGER, confirmed INTEGER DEFAULT 0)")
            con.execute(
                "CREATE TABLE IF NOT EXISTS tramos ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, pts TEXT, created_ts REAL, expires_ts REAL, "
                "closed_ts REAL, source TEXT, note TEXT, ref TEXT)")
            con.commit()
        return True
    except (sqlite3.Error, OSError):
        return False


def db_log(ev):
    return _db_run(
        "INSERT INTO eventos (ts, hora, nivel, fase, clave, mensaje, lat, lon) VALUES (?,?,?,?,?,?,?,?)",
        (ev.get("ts"), ev.get("hora"), ev.get("kind"), ev.get("phase", ""), ev.get("key"),
         ev.get("msg"), ev.get("lat"), ev.get("lon"))) is not None


def db_recent(limit=200):
    df = _db_query("SELECT hora, nivel, fase, mensaje, lat, lon FROM eventos ORDER BY id DESC LIMIT ?", (int(limit),))
    return df if not df.empty else pd.DataFrame(columns=["hora", "nivel", "fase", "mensaje", "lat", "lon"])


# ---- incidentes (memoria de 30 días) ----
def db_incident_open(kind, ref, now, lat, lon, msg, severity):
    open_ = _db_query("SELECT id FROM incidentes WHERE kind=? AND ref=? AND resolved_ts IS NULL", (kind, ref))
    if len(open_):
        _db_run("UPDATE incidentes SET last_ts=?, msg=?, lat=?, lon=? WHERE id=?",
                (now, msg, lat, lon, int(open_["id"].iloc[0])))
    else:
        _db_run("INSERT INTO incidentes (kind, ref, first_ts, last_ts, resolved_ts, lat, lon, msg, severity, confirmed) "
                "VALUES (?,?,?,?,NULL,?,?,?,?,0)", (kind, ref, now, now, lat, lon, msg, severity))


def db_incident_close(kind, ref, now):
    _db_run("UPDATE incidentes SET resolved_ts=?, last_ts=? WHERE kind=? AND ref=? AND resolved_ts IS NULL",
            (now, now, kind, ref))


def db_incident_confirm(ref):
    _db_run("UPDATE incidentes SET confirmed=1 WHERE kind='accident' AND ref=? AND resolved_ts IS NULL", (ref,))


def db_incident_dismiss(ref, now):
    _db_run("UPDATE incidentes SET confirmed=-1, resolved_ts=?, last_ts=? WHERE kind='accident' AND ref=? "
            "AND resolved_ts IS NULL", (now, now, ref))


def db_incidents(days=RETENTION_DAYS):
    df = _db_query("SELECT " + ", ".join(INC_COLUMNS) + " FROM incidentes WHERE last_ts >= ? ORDER BY first_ts DESC",
                   (time.time() - days * 86400,))
    return df if not df.empty else pd.DataFrame(columns=INC_COLUMNS)


# ---- tramos cortados ----
def db_cut_add(name, pts, source, note, expires_ts, ref=""):
    return _db_run("INSERT INTO tramos (name, pts, created_ts, expires_ts, closed_ts, source, note, ref) "
                   "VALUES (?,?,?,?,NULL,?,?,?)",
                   (name, json.dumps([[a, b] for a, b in pts]), time.time(), expires_ts, source, note, ref))


def db_cut_close(cut_id, now):
    _db_run("UPDATE tramos SET closed_ts=? WHERE id=? AND closed_ts IS NULL", (now, int(cut_id)))


def db_cut_ensure_auto(ref, name, pts, note):
    if len(_db_query("SELECT id FROM tramos WHERE ref=? AND closed_ts IS NULL", (ref,))):
        return False
    db_cut_add(name, pts, "auto", note, None, ref)
    return True


def db_cut_promote(ref):
    return bool(_db_run("UPDATE tramos SET source='manual' WHERE ref=? AND closed_ts IS NULL", (ref,)))


def db_cuts(active_only=True):
    if active_only:
        df = _db_query("SELECT * FROM tramos WHERE closed_ts IS NULL AND (expires_ts IS NULL OR expires_ts > ?) "
                       "ORDER BY created_ts DESC", (time.time(),))
    else:
        df = _db_query("SELECT * FROM tramos ORDER BY created_ts DESC LIMIT 200")
    out = []
    for r in df.to_dict("records"):
        try:
            r["pts"] = [(float(a), float(b)) for a, b in json.loads(r["pts"])]
        except (ValueError, TypeError):
            continue
        for k in ("expires_ts", "closed_ts"):
            if r.get(k) is not None and pd.isna(r[k]):
                r[k] = None
        out.append(r)
    return out


def db_purge(now):
    cutoff = now - RETENTION_DAYS * 86400
    _db_run("DELETE FROM incidentes WHERE last_ts < ?", (cutoff,))
    _db_run("DELETE FROM eventos WHERE ts < ?", (cutoff,))
    _db_run("DELETE FROM tramos WHERE closed_ts IS NOT NULL AND closed_ts < ?", (cutoff,))


# ==========================================
# 5. Seguimiento de trenes y reglas de alerta
# ==========================================
class TrainTracker:
    """
    Velocidad, rumbo, tiempo a baja velocidad y deceleración por tren (lógica pura, sin Streamlit).
    Protege contra lecturas duplicadas, feed congelado, saltos de GPS y huecos largos.
    """

    def __init__(self):
        self.state = {}
        self.fetch_count = 0
        self.last_df = pd.DataFrame(columns=BASE_COLUMNS)
        self.last_ts = None
        self.last_poll_ts = None
        self.last_change_ts = None
        self.duplicate_polls = 0
        self.frozen = False
        self.no_position = 0
        self.newest_gps_age = None  # edad (s) de la posición más reciente del feed
        self.raw_count = 0        # trenes que trae el feed (con o sin posición)
        self.brake_memory = {}
        self.hist = {}            # id -> deque[(ts, km/h)] para la telemetría por tren
        self.source_ts = None     # sello de tiempo del propio feed de Renfe

    def has_data(self):
        return self.last_ts is not None

    def frozen_for(self, now):
        if not self.frozen or self.last_change_ts is None:
            return 0.0
        return max(0.0, now - self.last_change_ts)

    def update(self, raw, stations_arr, fetched_at):
        if not raw or not isinstance(raw.get("trenes"), list):
            return self.last_df
        if self.last_poll_ts is not None and fetched_at <= self.last_poll_ts:
            return self.last_df
        self.last_poll_ts = fetched_at
        self.raw_count = len(raw.get("trenes") or [])

        prev_state = self.state
        new_state, rows = {}, []
        compared = moved = no_pos = 0
        points = {}

        for idx, t in enumerate(raw.get("trenes") or []):
            if not isinstance(t, dict):
                no_pos += 1
                continue
            lat, lon = to_float(t.get("latitud")), to_float(t.get("longitud"))
            if lat is None or lon is None:
                no_pos += 1
                continue

            t_id = str(t.get("codComercial") or t.get("mat") or f"idx{idx}")
            if t_id in new_state:
                t_id = f"{t_id}#{idx}"

            cod_p = t.get("codProduct")
            try:
                cod_key = int(cod_p)
            except (TypeError, ValueError):
                cod_key = cod_p

            prev = prev_state.get(t_id)
            speed, inst, state_speed = 0.0, None, None
            heading, has_heading, slow_since = 0.0, False, None
            prev_inst, decel = None, 0.0

            if prev:
                heading, has_heading = prev["heading"], prev["has_heading"]
                dt = fetched_at - prev["ts"]
                if dt >= 1:
                    dist = haversine(prev["lat"], prev["lon"], lat, lon)
                    compared += 1
                    if dist > 1:
                        moved += 1
                    inst_raw = (dist / dt) * 3.6
                    if dt > MAX_GAP_S:
                        if dist > MIN_MOVE_M:
                            heading, has_heading = get_heading(prev["lat"], prev["lon"], lat, lon), True
                    elif inst_raw > GLITCH_KMH:
                        speed = prev["speed"] or 0.0
                        state_speed, inst, slow_since = prev["speed"], prev.get("inst"), prev["slow_since"]
                    else:
                        inst = inst_raw
                        prev_inst = prev.get("inst")
                        if prev_inst is not None:
                            decel = (prev_inst - inst) / 3.6 / dt
                        speed = inst if prev["speed"] is None else \
                            SPEED_SMOOTH * inst + (1 - SPEED_SMOOTH) * prev["speed"]
                        state_speed = speed
                        if dist > MIN_MOVE_M:
                            heading, has_heading = get_heading(prev["lat"], prev["lon"], lat, lon), True
                        if speed < SLOW_KMH:
                            slow_since = prev["slow_since"] if prev["slow_since"] is not None else prev["ts"]
                else:
                    speed = prev["speed"] or 0.0
                    state_speed, inst, slow_since = prev["speed"], prev.get("inst"), prev["slow_since"]

            stopped_for = (fetched_at - slow_since) if slow_since is not None else 0.0

            dist_to_station = None
            braking_candidate = prev_inst is not None and prev_inst >= 60 and decel >= 0.4
            if slow_since is not None or braking_candidate:
                dist_to_station = nearest_station_m(lat, lon, stations_arr)

            new_state[t_id] = {"lat": lat, "lon": lon, "ts": fetched_at, "speed": state_speed, "inst": inst,
                               "heading": heading, "has_heading": has_heading, "slow_since": slow_since}

            retraso = to_float(t.get("ultRetraso"))
            retraso = int(retraso) if retraso is not None else 0
            hs = str(t.get("horaLlegadaSigEst") or "")
            tm = to_float(t.get("time"))
            gps_age = None
            if tm is not None and tm > 0:
                tm = tm / 1000.0 if tm > 1e11 else tm
                age = fetched_at - tm
                gps_age = round(max(0, age)) if age < 86400 else None
            points[t_id] = (fetched_at, round(speed, 1))

            rows.append({
                "cod_comercial": t_id, "tipo": NOM_PROD.get(cod_key, f"Cód. {cod_p}"),
                "grupo": grupo_de(cod_key), "cod_prod": cod_key,
                "lat": lat, "lon": lon, "retraso_min": retraso, "speed_kmh": round(speed, 1),
                "inst_kmh": round(inst, 1) if inst is not None else 0.0,
                "prev_inst_kmh": round(prev_inst, 1) if prev_inst is not None else 0.0,
                "decel_ms2": round(decel, 2), "heading": heading, "has_heading": has_heading,
                "stopped_for_s": round(stopped_for),
                "dist_to_station": round(dist_to_station) if dist_to_station is not None else None,
                "est_ant": norm_code(t.get("codEstAnt")), "est_sig": norm_code(t.get("codEstSig")),
                "origen": norm_code(t.get("codOrigen")), "destino": norm_code(t.get("codDestino")),
                "hora_sig": hs[11:16] if len(hs) >= 16 else "", "gps_age_s": gps_age,
                "mat": t.get("mat", ""), "accesible": bool(t.get("accesible", False)),
            })

        # Lectura duplicada: el feed no cambió => NO significa que los trenes estén parados
        if compared >= 10 and moved == 0:
            self.duplicate_polls += 1
            ref = self.last_change_ts if self.last_change_ts is not None else fetched_at
            self.frozen = (fetched_at - ref) > FROZEN_AFTER_S
            return self.last_df

        self.state = new_state
        self.fetch_count += 1
        self.last_ts = fetched_at
        self.last_change_ts = fetched_at
        self.duplicate_polls = 0
        self.frozen = False
        self.no_position = no_pos
        ages = [r["gps_age_s"] for r in rows if r["gps_age_s"] is not None]
        self.newest_gps_age = min(ages) if ages else None
        self.source_ts = parse_iso_ts(raw.get("fechaActualizacion"))
        for k, pt in points.items():
            self.hist.setdefault(k, deque(maxlen=40)).append(pt)
        self.hist = {k: v for k, v in self.hist.items() if k in points}
        self.last_df = pd.DataFrame(rows, columns=BASE_COLUMNS) if rows else pd.DataFrame(columns=BASE_COLUMNS)
        return self.last_df


def apply_stop_rules(df, cfg, brake_memory=None, now=None):
    """Marca is_stopped / is_suspect (aviso temprano) / braking según los parámetros actuales."""
    df = df.copy()
    if df.empty:
        for c in RULE_COLUMNS:
            df[c] = pd.Series(dtype=bool)
        return df
    dist = pd.to_numeric(df["dist_to_station"], errors="coerce")
    age = pd.to_numeric(df["gps_age_s"], errors="coerce")
    fresh = ~(age > cfg.get("gps_stale_s", 600))   # sin dato de edad => se considera fresco
    far = dist.notna() & (dist > cfg["station_radius_m"]) & fresh
    sf = df["stopped_for_s"]
    df["is_stopped"] = ((sf >= cfg["min_stop_s"]) & far).astype(bool)
    df["is_suspect"] = ((sf >= cfg["early_stop_s"]) & (sf < cfg["min_stop_s"]) & far).astype(bool)

    cand = ((df["prev_inst_kmh"] >= cfg["brake_min_kmh"]) & (df["decel_ms2"] >= cfg["brake_ms2"])
            & dist.notna() & (dist > cfg["brake_station_m"]) & fresh)
    if brake_memory is not None and now is not None:
        for cod in df.loc[cand, "cod_comercial"]:
            brake_memory[cod] = now + cfg["brake_hold_s"]
        for cod in [c for c, until in brake_memory.items() if until <= now]:
            del brake_memory[cod]
        braking = df["cod_comercial"].map(lambda c: brake_memory.get(c, 0) > now)
    else:
        braking = cand
    df["braking"] = braking.astype(bool)
    return df


def check_proximity_risk(df, cfg):
    alerts = []
    if df.empty:
        return alerts
    target_mask = df["is_stopped"] == True  # noqa: E712
    if cfg.get("risk_include_suspect", True):
        target_mask = target_mask | (df["is_suspect"] == True)  # noqa: E712
    stopped = df[target_mask]
    moving = df[(df["is_stopped"] == False) & (df["is_suspect"] == False)  # noqa: E712
                & (df["speed_kmh"] > max(1, cfg["risk_min_kmh"])) & (df["has_heading"] == True)]  # noqa: E712
    if stopped.empty or moving.empty:
        return alerts

    for _, m in moving.iterrows():
        for _, s in stopped.iterrows():
            dist = haversine(m["lat"], m["lon"], s["lat"], s["lon"])
            if dist < cfg["risk_dist_m"]:
                brng = get_heading(m["lat"], m["lon"], s["lat"], s["lon"])
                diff = abs(m["heading"] - brng)
                if diff > 180:
                    diff = 360 - diff
                if diff < cfg["risk_heading_deg"]:
                    ttc = dist / (m["speed_kmh"] / 3.6)
                    if ttc < cfg["risk_ttc_s"]:
                        alerts.append({"moving": m["cod_comercial"], "stopped": s["cod_comercial"],
                                       "dist_m": round(dist), "speed_kmh": round(m["speed_kmh"]),
                                       "ttc_s": round(ttc), "lat": float(s["lat"]), "lon": float(s["lon"])})
    alerts.sort(key=lambda a: a["ttc_s"])
    return alerts


def segment_for_train(row, info, half_m):
    """Tramo probable afectado: ±half_m alrededor del tren, orientado según su ruta (aprox.)."""
    a, b = info.get(row["est_ant"]), info.get(row["est_sig"])
    if a and b and (a["lat"], a["lon"]) != (b["lat"], b["lon"]):
        brg = get_heading(a["lat"], a["lon"], b["lat"], b["lon"])
        where = f"entre {label_est(row['est_ant'], info)} y {label_est(row['est_sig'], info)}"
    else:
        brg = row["heading"] if row["has_heading"] else 90.0
        where = "en vía"
    p1 = offset_point(row["lat"], row["lon"], brg + 180, half_m)
    p2 = offset_point(row["lat"], row["lon"], brg, half_m)
    return [p1, p2], f"Zona del tren {row['cod_comercial']} ({where})"


def detect_accidents(df, risk_alerts, cfg, dismissed=()):
    """Posible accidente: tren detenido lejos de estación Y (frenada brusca previa, o tiempo largo, o riesgo de alcance)."""
    out = []
    if df.empty:
        return out
    targets = {a["stopped"] for a in risk_alerts}
    for _, s in df[df["is_stopped"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        if cod in dismissed:
            continue
        why = []
        if bool(s["braking"]):
            why.append("frenada brusca previa")
        if s["stopped_for_s"] >= cfg.get("accident_s", 240):
            why.append(f"{int(s['stopped_for_s'])} s detenido lejos de estación")
        if cod in targets:
            why.append("otro tren se aproxima")
        if why:
            out.append({"cod": cod, "tipo": s["tipo"], "why": why, "lat": float(s["lat"]), "lon": float(s["lon"])})
    return out


def check_cut_risk(df, cuts, cfg):
    """Trenes en marcha que se dirigen a un tramo cortado."""
    alerts = []
    if df.empty or not cuts:
        return alerts
    moving = df[(df["is_stopped"] == False) & (df["speed_kmh"] > max(1, cfg["risk_min_kmh"]))  # noqa: E712
                & (df["has_heading"] == True)]  # noqa: E712
    for _, m in moving.iterrows():
        for c in cuts:
            pt, d = path_nearest(m["lat"], m["lon"], c["pts"])
            if pt is None or d > cfg.get("cut_warn_m", 10000):
                continue
            diff = 0.0
            if d > 400:
                diff = abs(m["heading"] - get_heading(m["lat"], m["lon"], pt[0], pt[1]))
                diff = 360 - diff if diff > 180 else diff
            if diff < cfg["risk_heading_deg"]:
                ttc = d / (m["speed_kmh"] / 3.6)
                if d <= 400 or ttc < cfg["risk_ttc_s"] * 2:
                    alerts.append({"moving": m["cod_comercial"], "cut_id": c["id"], "cut_name": c["name"],
                                   "dist_m": round(d), "speed_kmh": round(m["speed_kmh"]), "ttc_s": round(ttc),
                                   "lat": float(pt[0]), "lon": float(pt[1])})
    alerts.sort(key=lambda a: a["ttc_s"])
    return alerts


def compute_risk(df, risk_alerts, cut_alerts, acc, cfg):
    """Índice de riesgo 0-100 por tren y motivos."""
    out = {}
    if df.empty:
        return out

    def bump(c, v, why):
        e = out.setdefault(c, {"score": 0, "why": []})
        e["score"] = min(100, e["score"] + v)
        e["why"].append(why)

    for _, r in df.iterrows():
        c = r["cod_comercial"]
        out[c] = {"score": 0, "why": []}
        if r["is_stopped"]:
            bump(c, 55, "DETENIDO")
        elif r["is_suspect"]:
            bump(c, 30, "AVISO")
        if r["braking"]:
            bump(c, 20, "FRENADA")
        if pd.notna(r["gps_age_s"]) and r["gps_age_s"] > 180:
            bump(c, 10, "SIN GPS")
        if r["retraso_min"] >= 30:
            bump(c, 5, "RETRASO")
    for a in risk_alerts:
        urg = max(0.0, 1 - a["ttc_s"] / max(1, cfg["risk_ttc_s"]))
        bump(a["moving"], int(40 + 30 * urg), "ALCANCE")
        bump(a["stopped"], 25, "ALCANZABLE")
    for a in cut_alerts:
        urg = max(0.0, 1 - a["ttc_s"] / max(1, cfg["risk_ttc_s"] * 2))
        bump(a["moving"], int(45 + 25 * urg), "TRAMO CORTADO")
    for a in acc:
        bump(a["cod"], 30, "ACCIDENTE")
    return out


def risk_level(score):
    if score >= 80:
        return "CRÍTICO", "crit", "#ff3232"
    if score >= 55:
        return "ALTO", "high", "#ff9f1a"
    if score >= 30:
        return "MEDIO", "mid", "#f1c40f"
    return "BAJO", "low", "#39ff88"


def analyze(df, cfg, cuts, dismissed=()):
    risk = check_proximity_risk(df, cfg)
    acc = detect_accidents(df, risk, cfg, dismissed)
    cut = check_cut_risk(df, cuts, cfg)
    return {"risk": risk, "acc": acc, "cut": cut, "scores": compute_risk(df, risk, cut, acc, cfg)}


def make_event(kind, key, msg, speak=None, lat=None, lon=None, subject=None):
    return {"kind": kind, "key": key, "msg": msg, "speak": speak or msg,
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None, "subject": subject or msg}


def build_events(df, risk_alerts, cut_alerts=(), accidents=(), info=None):
    events = []
    if df.empty:
        return events
    for _, s in df[df["is_stopped"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        events.append(make_event(
            "stopped", f"stopped|{cod}",
            f"Tren {cod} ({s['tipo']}) detenido en vía a {fmt_m(s['dist_to_station'])} m de la estación más cercana, "
            f"{int(s['stopped_for_s'])} s a baja velocidad (retraso {int(s['retraso_min'])} min).",
            speak=f"Tren {cod} detenido en vía", lat=s["lat"], lon=s["lon"], subject=f"Tren {cod} detenido en vía"))
    for _, s in df[df["is_suspect"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        events.append(make_event(
            "early", f"early|{cod}",
            f"Posible detención: tren {cod} ({s['tipo']}) lleva {int(s['stopped_for_s'])} s a baja velocidad, "
            f"a {fmt_m(s['dist_to_station'])} m de la estación más cercana.",
            speak=f"Aviso temprano. Tren {cod} posiblemente detenido", lat=s["lat"], lon=s["lon"],
            subject=f"Tren {cod} posible detención"))
    for _, s in df[df["braking"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        events.append(make_event(
            "brake", f"brake|{cod}",
            f"Frenada brusca (heurística): tren {cod} ({s['tipo']}) bajó de {s['prev_inst_kmh']:.0f} a "
            f"{s['inst_kmh']:.0f} km/h ({s['decel_ms2']:.2f} m/s²) lejos de estaciones.",
            speak=f"Frenada brusca del tren {cod}", lat=s["lat"], lon=s["lon"], subject=f"Tren {cod} frenada brusca"))
    for a in risk_alerts:
        events.append(make_event(
            "risk", f"risk|{a['moving']}|{a['stopped']}",
            f"Tren {a['moving']} ({a['speed_kmh']} km/h) se acerca al tren {a['stopped']} detenido: "
            f"{a['dist_m']} m, TTC {a['ttc_s']} s.",
            speak=f"Riesgo crítico. Tren {a['moving']} se acerca al tren {a['stopped']} detenido. {a['ttc_s']} segundos.",
            lat=a["lat"], lon=a["lon"], subject=f"Riesgo {a['moving']} hacia {a['stopped']}"))
    for a in cut_alerts:
        events.append(make_event(
            "risk", f"cutrisk|{a['moving']}|{a['cut_id']}",
            f"Tren {a['moving']} ({a['speed_kmh']} km/h) se dirige al tramo cortado «{a['cut_name']}»: "
            f"{a['dist_m']} m, TTC {a['ttc_s']} s.",
            speak=f"Atención. Tren {a['moving']} se dirige a un tramo cortado. {a['ttc_s']} segundos.",
            lat=a["lat"], lon=a["lon"], subject=f"Tren {a['moving']} hacia tramo cortado"))
    for a in accidents:
        events.append(make_event(
            "accident", f"accident|{a['cod']}",
            f"POSIBLE ACCIDENTE: tren {a['cod']} ({a['tipo']}) detenido en vía — {', '.join(a['why'])}.",
            speak=f"Posible accidente. Tren {a['cod']} detenido en vía", lat=a["lat"], lon=a["lon"],
            subject=f"Posible accidente del tren {a['cod']}"))
    return events


# ==========================================
# 6. Canales de comunicación (Telegram · ntfy · Webhook)
# ==========================================
CHANNEL_ENV = {"telegram_token": "TELEGRAM_BOT_TOKEN", "telegram_chat": "TELEGRAM_CHAT_ID",
               "webhook_url": "ALERT_WEBHOOK_URL", "ntfy_topic": "NTFY_TOPIC", "ntfy_server": "NTFY_SERVER",
               "adif_url": "ADIF_INCIDENTS_URL"}


def read_channel_defaults():
    out = {}
    for key, env in CHANNEL_ENV.items():
        val = None
        try:
            val = st.secrets.get(env)
        except Exception:  # noqa: BLE001 - sin secrets.toml Streamlit lanza distintas excepciones
            val = None
        val = val or os.getenv(env)
        if val:
            out[key] = str(val).strip()
    out.setdefault("ntfy_server", "https://ntfy.sh")
    return out


def event_text(ev):
    lvl = LEVELS[ev["kind"]]
    lines = [f"{lvl['icon']} {lvl['label']}", ev["msg"], f"🕒 {ev.get('hora', '')}"]
    if ev.get("lat") is not None and ev.get("lon") is not None:
        lines.append(f"🗺 https://www.google.com/maps?q={ev['lat']:.5f},{ev['lon']:.5f}")
    return "\n".join(lines)


def safe_error(exc):
    """Descripción del error SIN la URL (la de Telegram contiene el token)."""
    msg = type(exc).__name__
    resp = getattr(exc, "response", None)
    if resp is not None:
        msg += f" HTTP {resp.status_code}"
    return msg


def send_telegram(token, chat, text, lat=None, lon=None):
    base = f"https://api.telegram.org/bot{token}"
    r = requests.post(f"{base}/sendMessage",
                      json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=8)
    r.raise_for_status()
    if lat is not None and lon is not None:
        try:
            requests.post(f"{base}/sendLocation", json={"chat_id": chat, "latitude": lat, "longitude": lon}, timeout=8)
        except requests.RequestException:
            pass


NTFY_PRIORITY = {"accident": 5, "risk": 5, "stopped": 4, "brake": 3, "early": 3, "system": 2, "resolved": 2}
NTFY_TAGS = {"accident": "boom,rotating_light,train", "risk": "rotating_light,train", "stopped": "red_circle,train", "brake": "warning,train",
             "early": "warning,train", "system": "gear", "resolved": "white_check_mark"}


def send_ntfy(server, topic, ev, text):
    headers = {"Title": ascii_safe(LEVELS[ev["kind"]]["label"]),
               "Priority": str(NTFY_PRIORITY.get(ev["kind"], 3)), "Tags": NTFY_TAGS.get(ev["kind"], "train")}
    r = requests.post(f"{server.rstrip('/')}/{topic}", data=text.encode("utf-8"), headers=headers, timeout=8)
    r.raise_for_status()


def send_webhook(url, ev, text):
    payload = {"text": text, "content": text, "level": ev["kind"], "title": LEVELS[ev["kind"]]["label"],
               "message": ev["msg"], "lat": ev.get("lat"), "lon": ev.get("lon"), "time": ev.get("hora")}
    r = requests.post(url, json=payload, timeout=8)
    r.raise_for_status()


def send_all(channels, ev, text):
    """Envía por todos los canales configurados. Devuelve [(canal, ok, detalle)]."""
    results = []
    tok, chat = channels.get("telegram_token"), channels.get("telegram_chat")
    if tok and chat:
        try:
            send_telegram(tok, chat, text, ev.get("lat"), ev.get("lon"))
            results.append(("Telegram", True, "ok"))
        except (requests.RequestException, ValueError) as e:
            results.append(("Telegram", False, safe_error(e)))
    topic = channels.get("ntfy_topic")
    if topic:
        try:
            send_ntfy(channels.get("ntfy_server") or "https://ntfy.sh", topic, ev, text)
            results.append(("ntfy", True, "ok"))
        except (requests.RequestException, ValueError) as e:
            results.append(("ntfy", False, safe_error(e)))
    hook = channels.get("webhook_url")
    if hook:
        try:
            send_webhook(hook, ev, text)
            results.append(("Webhook", True, "ok"))
        except (requests.RequestException, ValueError) as e:
            results.append(("Webhook", False, safe_error(e)))
    return results


def should_push(ev, cfg):
    kind = ev["kind"]
    if kind == "system":
        return True
    if kind == "resolved":
        return cfg["push_min_rank"] <= 3
    return LEVELS[kind]["rank"] >= cfg["push_min_rank"]


# ==========================================
# 7. Monitor en segundo plano (funciona sin ninguna pestaña abierta)
# ==========================================
def _where(exc):
    """Archivo:línea donde ocurrió una excepción (para diagnóstico en pantalla)."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    return f"línea {tb.tb_lineno}" if tb else "?"


def diagnose_connection():
    """Prueba directa de las dos fuentes de datos. Devuelve [(nombre, ok, detalle)]."""
    out = []
    for name, url, params in (("Feed de trenes", URL_FLOTA, {"v": int(time.time() * 1000)}),
                              ("Estaciones", URL_ESTACIONES, None), ("Rutas y horarios", URL_RUTAS, None)):
        t0 = time.time()
        try:
            r = requests.get(url, params=params, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            ms = int((time.time() - t0) * 1000)
            if r.status_code != 200:
                out.append((name, False, f"HTTP {r.status_code} en {ms} ms"))
                continue
            data = r.json()
            if name.startswith("Rutas"):
                rt = parse_routes(data)
                out.append((name, bool(rt), f"HTTP 200 en {ms} ms · {len(rt)} trenes con paradas reconocidas · "
                                            f"campos: {routes_debug(data, rt)['campos']}"))
                continue
            n = len(data.get("trenes", [])) if name.startswith("Feed") else len(data.get("features", []))
            out.append((name, True, f"HTTP 200 en {ms} ms · {n} {'trenes' if name.startswith('Feed') else 'estaciones'}"))
        except requests.RequestException as e:
            out.append((name, False, f"{type(e).__name__}: {str(e)[:140]}"))
        except ValueError:
            out.append((name, False, "respuesta que no es JSON (¿bloqueo, proxy o página de error?)"))
    return out


INCIDENT_KINDS = ("brake", "stopped", "risk", "accident")
SEVERITY = {"brake": 1, "stopped": 2, "risk": 3, "accident": 4}


class Monitor:
    """
    Motor global (uno por servidor): sondea Renfe en un hilo propio, detecta avisos tempranos, detenciones,
    frenadas, riesgo, posibles accidentes y trenes que se dirigen a tramos cortados. Registra todo en SQLite
    (memoria de 30 días) y lo envía a Telegram/ntfy/webhook. Las pestañas solo leen su estado.
    """

    def __init__(self, demo=False):
        self.demo = demo
        self.lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self.cfg = dict(DEFAULT_CFG)
        self.channels = {}
        self.stations = []
        self.station_info = {}
        self.stations_arr = np.empty((0, 2))
        self.stations_ts = 0.0
        self.stations_try_ts = 0.0
        self.stations_error = None
        self.routes = {}
        self.routes_dbg = None
        self.routes_error = None
        self.routes_try_ts = 0.0
        self.last_error_detail = None
        self.tracker = TrainTracker()
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "Mozilla/5.0"})
        self.poll_s = 4 if demo else DEFAULT_POLL_S
        self.last_tick = 0.0
        self.last_error = None
        self.consecutive_errors = 0
        self.latency_ms = None
        self.events_seq = 0
        self.events = deque(maxlen=300)
        self.alert_state = {}
        self.active = []
        self.deliveries = deque(maxlen=40)
        self.incidents = []
        self.adif_cuts = []
        self.inc_ok = None
        self.inc_try_ts = 0.0
        self.dismissed = set()
        self.net_hist = deque(maxlen=360)
        self._last_fc = 0
        self.last_purge = 0.0
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="notif")
        self.thread = None
        self.stop_flag = threading.Event()
        self.wake = threading.Event()
        self.db_ok = False if demo else db_init()   # la demo no toca la base de datos real
        self.cuts = db_cuts() if self.db_ok else []

    # ---- ciclo de vida ----
    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_flag.clear()
            self.thread = threading.Thread(target=self._loop, name="ebm-monitor", daemon=True)
            self.thread.start()

    def ensure_running(self):
        if self.thread is None or not self.thread.is_alive():
            self.start()

    def stop(self):
        self.stop_flag.set()
        self.wake.set()

    def poll_now(self):
        self.wake.set()

    def _loop(self):
        while not self.stop_flag.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - el hilo nunca debe morir por un fallo puntual
                with self.lock:
                    self.last_error = type(e).__name__
                    self.last_error_detail = f"{type(e).__name__}: {str(e)[:160]} (en {_where(e)})"
            self.wake.wait(max(2, self.poll_s))
            self.wake.clear()

    # ---- configuración ----
    def set_cfg(self, cfg):
        with self.lock:
            self.cfg.update(cfg)

    def set_poll(self, seconds):
        if not self.demo:
            self.poll_s = max(2, int(seconds))

    def update_channels(self, values):
        with self.lock:
            for k, v in values.items():
                if v and str(v).strip():
                    self.channels[k] = str(v).strip()

    def channel_names(self):
        with self.lock:
            ch = dict(self.channels)
        names = []
        if ch.get("telegram_token") and ch.get("telegram_chat"):
            names.append("Telegram")
        if ch.get("ntfy_topic"):
            names.append("ntfy")
        if ch.get("webhook_url"):
            names.append("Webhook")
        return names

    def set_stations(self, stations):
        with self.lock:
            self.stations = list(stations)
            self.station_info = {s["code"]: s for s in self.stations if s.get("code")}
            self.stations_arr = np.array([[s["lat"], s["lon"]] for s in self.stations], dtype=float) \
                if self.stations else np.empty((0, 2))
            self.stations_ts = time.time()

    def has_stations(self):
        return len(self.stations) > 0

    # ---- tramos cortados ----
    def all_cuts(self):
        with self.lock:
            return list(self.cuts) + list(self.adif_cuts)

    def reload_cuts(self):
        with self.lock:
            if self.db_ok:
                self.cuts = db_cuts()

    def add_cut(self, name, pts, hours=None, note="", source="manual", ref=""):
        if not self.db_ok or len(pts) < 2:
            return False
        exp = time.time() + hours * 3600 if hours else None
        db_cut_add(name or "Tramo cortado", pts, source, note, exp, ref)
        self.reload_cuts()
        return True

    def close_cut(self, cut_id):
        db_cut_close(cut_id, time.time())
        self.reload_cuts()

    def _train_row(self, cod):
        df = self.tracker.last_df
        m = df[df["cod_comercial"] == cod] if not df.empty else df
        return None if m.empty else m.iloc[0]

    def cut_from_train(self, cod):
        with self.lock:
            row = self._train_row(cod)
            if row is None:
                return None
            pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
            return name if self.add_cut(name, pts, None, "Cierre manual desde el tren", "manual", f"man|{cod}") else None

    def confirm_accident(self, cod):
        """Confirma un accidente: queda registrado y su tramo pasa a cortado manual (hasta reabrirlo)."""
        with self.lock:
            row = self._train_row(cod)
            if row is None or not self.db_ok:
                return False
            now = time.time()
            db_incident_open("accident", cod, now, float(row["lat"]), float(row["lon"]),
                             f"Accidente confirmado manualmente: tren {cod}", SEVERITY["accident"])
            db_incident_confirm(cod)
            if not db_cut_promote(f"auto|{cod}"):
                pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
                db_cut_add(name, pts, "manual", "Accidente confirmado", None, f"acc|{cod}")
            self.reload_cuts()
            return True

    def dismiss_accident(self, cod):
        """Falsa alarma: no se vuelve a levantar mientras el tren siga en esa situación."""
        with self.lock:
            now = time.time()
            self.dismissed.add(cod)
            if self.db_ok:
                db_incident_dismiss(cod, now)
                for c in self.cuts:
                    if c.get("ref") == f"auto|{cod}":
                        db_cut_close(c["id"], now)
                self.reload_cuts()
            return True

    # ---- obtención de datos ----
    def _get_json(self, url, params=None):
        r = self.http.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def tick(self):
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            now = time.time()
            if self.db_ok and now - self.last_purge > 6 * 3600:
                self.last_purge = now
                db_purge(now)
            stale_stations = (now - self.stations_ts) > 3600
            if (not self.stations or stale_stations) and (now - self.stations_try_ts) > 60:
                self.stations_try_ts = now
                try:
                    stations = parse_stations(self._get_json(URL_ESTACIONES))
                    if stations:
                        self.set_stations(stations)
                        self.stations_error = None
                        save_stations_cache(stations)
                    else:
                        self.stations_error = "el archivo no contiene estaciones (formato distinto)"
                except (requests.RequestException, ValueError) as e:
                    self.stations_error = safe_error(e)
                if not self.stations:
                    cached = load_stations_cache()
                    if cached:
                        self.set_stations(cached)
                        self.stations_error = (self.stations_error or "sin descarga") + " · usando copia guardada"
            try:
                t0 = time.time()
                raw = demo_feed(now) if self.demo else self._get_json(URL_FLOTA, {"v": int(now * 1000)})
                self.latency_ms = int((time.time() - t0) * 1000)
                if not (isinstance(raw, dict) and "trenes" in raw):
                    raise ValueError("feed sin 'trenes'")
            except (requests.RequestException, ValueError) as e:
                with self.lock:
                    self.consecutive_errors += 1
                    self.last_error = type(e).__name__
                    self.last_error_detail = f"{type(e).__name__}: {str(e)[:160]}"
                    self._evaluate(time.time())
            else:
                self.ingest(raw, time.time())
            self._poll_incidents(time.time())
            self._poll_routes(time.time())
        finally:
            self._tick_lock.release()

    def _poll_routes(self, now):
        """Rutas con horarios de cada tren (para la hora de llegada al destino). Cada 5 min."""
        if self.demo or (now - self.routes_try_ts) < 300:
            return
        self.routes_try_ts = now
        try:
            data = self._get_json(URL_RUTAS)
            routes = parse_routes(data)
            with self.lock:
                self.routes, self.routes_dbg = routes, routes_debug(data, routes)
                self.routes_error = None if routes else "el archivo se leyó pero no reconocí las paradas (ver campos en SISTEMA)"
        except (requests.RequestException, ValueError) as e:
            with self.lock:
                self.routes_error = safe_error(e)

    def _poll_incidents(self, now):
        url = self.channels.get("adif_url")
        if not url or (now - self.inc_try_ts) < 180:
            return
        self.inc_try_ts = now
        try:
            items = parse_incidents(self._get_json(url))
            cuts = [{"id": f"adif{i}", "name": it["titulo"], "pts": it["pts"], "source": "adif",
                     "note": it["texto"], "created_ts": now, "expires_ts": None, "ref": ""}
                    for i, it in enumerate(items) if it["pts"]]
            with self.lock:
                self.incidents, self.adif_cuts, self.inc_ok = items, cuts, True
        except (requests.RequestException, ValueError):
            with self.lock:
                self.inc_ok = False

    def ingest(self, raw, fetched_at):
        with self.lock:
            self.tracker.update(raw, self.stations_arr, fetched_at)
            self.consecutive_errors = 0
            self.last_error = None
            self.last_tick = time.time()
            self._evaluate(fetched_at)

    # ---- evaluación y avisos ----
    def _sync_auto_cuts(self, df, acc, now):
        """Cada posible accidente corta automáticamente su tramo; se reabre solo cuando deja de detectarse."""
        refs = {f"auto|{a['cod']}" for a in acc}
        if not self.db_ok:
            if not self.demo:
                return False
            before = len(self.cuts)  # demo: tramos automáticos solo en memoria
            have = {c.get("ref") for c in self.cuts}
            for a in acc:
                if f"auto|{a['cod']}" not in have:
                    row = df[df["cod_comercial"] == a["cod"]].iloc[0]
                    pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
                    self.cuts.append({"id": f"demo{len(self.cuts) + 1}", "name": name, "pts": pts, "source": "auto",
                                      "note": "Demo: cierre automático", "created_ts": now, "expires_ts": None,
                                      "ref": f"auto|{a['cod']}"})
            self.cuts = [c for c in self.cuts if c.get("ref") in refs]
            return before != len(self.cuts) or bool(refs - have)
        changed = False
        for a in acc:
            row = df[df["cod_comercial"] == a["cod"]].iloc[0]
            pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
            if db_cut_ensure_auto(f"auto|{a['cod']}", name, pts, "Cierre automático por posible accidente (aprox.)"):
                changed = True
        for c in self.cuts:
            if c.get("source") == "auto" and c.get("ref") not in refs:
                db_cut_close(c["id"], now)
                changed = True
        if changed:
            self.cuts = db_cuts()
        return changed

    def _evaluate(self, now):
        tr = self.tracker
        sys_events = []
        if tr.frozen:
            sys_events.append(make_event(
                "system", "sys|frozen",
                f"El feed de Renfe no se actualiza desde hace {int(tr.frozen_for(now))} s: detección en pausa.",
                speak="El feed de Renfe no se actualiza", subject="Feed de Renfe"))
        if self.consecutive_errors >= 3:
            sys_events.append(make_event(
                "system", "sys|conn",
                f"Sin conexión con Renfe ({self.consecutive_errors} fallos seguidos). Se usa la última lectura.",
                speak="Sin conexión con Renfe", subject="Conexión con Renfe"))
        hold = bool(sys_events)
        events = []
        if not hold and tr.has_data():
            df = apply_stop_rules(tr.last_df, self.cfg, tr.brake_memory, tr.last_ts)
            an = analyze(df, self.cfg, self.all_cuts(), self.dismissed)
            self.dismissed &= set(df.loc[df["is_stopped"] == True, "cod_comercial"])  # noqa: E712
            if self._sync_auto_cuts(df, an["acc"], now):
                an = analyze(df, self.cfg, self.all_cuts(), self.dismissed)
            events = build_events(df, an["risk"], an["cut"], an["acc"], self.station_info)
            self._record_stats(df, an)
        self._process_events(sys_events + events, now, hold)

    def _record_stats(self, df, an):
        tr = self.tracker
        if tr.fetch_count == self._last_fc or df.empty:
            return
        self._last_fc = tr.fetch_count
        moving = df.loc[df["speed_kmh"] > SLOW_KMH, "speed_kmh"]
        self.net_hist.append({
            "ts": tr.last_ts, "trenes": len(df), "retrasados": int((df["retraso_min"] >= 5).sum()),
            "lentos": int((df["speed_kmh"] < SLOW_KMH).sum()), "detenidos": int(df["is_stopped"].sum()),
            "vel_media": float(moving.mean()) if len(moving) else 0.0,
            "riesgo": max((v["score"] for v in an["scores"].values()), default=0)})

    def _record(self, ev, now):
        if self.db_ok and ev["kind"] in INCIDENT_KINDS:
            db_incident_open(ev["kind"], ev["key"].split("|", 1)[1], now, ev.get("lat"), ev.get("lon"),
                             ev["msg"], SEVERITY[ev["kind"]])

    def _on_cleared(self, kind, key, now):
        if self.db_ok and kind in INCIDENT_KINDS:
            db_incident_close(kind, key.split("|", 1)[1], now)

    def _process_events(self, events, now, hold=False):
        fired, new_state = [], {}
        for ev in events:
            k, lvl = ev["key"], LEVELS[ev["kind"]]
            st_ = self.alert_state.get(k)
            if st_ is None:
                new_state[k] = {"first": now, "last": now, "kind": ev["kind"], "ev": ev}
                fired.append(dict(ev, phase="nuevo"))
                self._record(ev, now)
            else:
                if now - st_["last"] >= lvl["repeat_s"]:
                    st_["last"] = now
                    fired.append(dict(ev, phase="persiste"))
                st_["ev"] = ev
                new_state[k] = st_
        for k, st_ in self.alert_state.items():
            if k in new_state:
                continue
            if hold and not k.startswith("sys|"):
                new_state[k] = st_  # con el feed en pausa no se resuelve nada
                continue
            self._on_cleared(st_["kind"], k, now)
            if st_["kind"] in ("stopped", "risk", "system", "accident"):
                old = st_["ev"]
                fired.append(make_event(
                    "resolved", f"resolved|{k}", f"Resuelto — {old['subject']}: ya no se detecta la situación.",
                    speak=f"Resuelto. {old['subject']}", lat=old.get("lat"), lon=old.get("lon"),
                    subject=old["subject"]) | {"phase": "resuelto"})
        self.alert_state = new_state
        self.active = [dict(s["ev"], first=s["first"]) for s in new_state.values()]
        self._publish(fired)

    def _publish(self, fired):
        if not fired:
            return
        mass_keys, summary = set(), None
        mass = [e for e in fired if e["phase"] == "nuevo" and e["kind"] in ("early", "stopped", "brake")]
        if len(mass) > MASS_LIMIT:
            mass_keys = {e["key"] for e in mass}
            summary = make_event(
                "system", "sys|mass",
                f"{len(mass)} avisos simultáneos (posible fallo de datos del feed). "
                f"Primeros: {', '.join(e['subject'] for e in mass[:4])}…",
                speak="Muchos avisos simultáneos, posible fallo de datos")
        stamp = time.time()
        hora = datetime.now(TZ).strftime("%H:%M:%S")
        for e in fired + ([summary | {"phase": "resumen"}] if summary else []):
            self.events_seq += 1
            e["seq"], e["ts"], e["hora"] = self.events_seq, stamp, hora
            self.events.append(e)
            if self.db_ok:
                db_log(e)
            if e["key"] not in mass_keys and self.channels and not self.demo and should_push(e, self.cfg):
                self.pool.submit(self._deliver, e)

    def _deliver(self, ev):
        with self.lock:
            channels = dict(self.channels)
        results = send_all(channels, ev, event_text(ev))
        with self.lock:
            for canal, ok, detalle in results:
                self.deliveries.append({"hora": datetime.now(TZ).strftime("%H:%M:%S"), "canal": canal,
                                        "nivel": ev["kind"], "ok": ok, "detalle": detalle})
        return results

    def send_test(self):
        ev = make_event("system", "sys|test", "Prueba de canales de aviso: si lees esto, el canal funciona.")
        ev.update(seq=0, ts=time.time(), hora=datetime.now(TZ).strftime("%H:%M:%S"), phase="prueba")
        return self._deliver(ev)

    # ---- lectura para la interfaz ----
    def events_since(self, seq):
        with self.lock:
            return [dict(e) for e in self.events if e["seq"] > seq], self.events_seq

    def recent_events(self, limit=100):
        with self.lock:
            return list(self.events)[-limit:][::-1]

    def recent_deliveries(self):
        with self.lock:
            return list(self.deliveries)[::-1]

    def snapshot(self):
        with self.lock:
            tr = self.tracker
            if not tr.has_data():
                return None
            now = time.time()
            df = apply_stop_rules(tr.last_df, self.cfg, tr.brake_memory, tr.last_ts)
            return {
                "df": df, "fetched_at": tr.last_ts, "last_poll": tr.last_poll_ts,
                "stale": self.consecutive_errors > 0, "frozen": tr.frozen, "frozen_for": tr.frozen_for(now),
                "fetch_count": tr.fetch_count, "duplicate_polls": tr.duplicate_polls, "seq": self.events_seq,
                "active": list(self.active), "last_error": self.last_error, "no_position": tr.no_position,
                "raw_count": tr.raw_count, "demo": self.demo, "routes": self.routes, "routes_dbg": self.routes_dbg,
                "routes_error": self.routes_error, "stations_error": self.stations_error, "newest_gps_age": tr.newest_gps_age,
                "thread_alive": bool(self.thread and self.thread.is_alive()),
                "db_ok": self.db_ok, "poll_s": self.poll_s,
                "incidents": list(self.incidents), "inc_ok": self.inc_ok,
                "inc_cfg": bool(self.channels.get("adif_url")), "info": self.station_info,
                "cuts": self.all_cuts(), "dismissed": set(self.dismissed),
                "latency_ms": self.latency_ms, "source_ts": tr.source_ts,
                "hist": {k: [p[1] for p in v] for k, v in tr.hist.items()},
                "net_hist": list(self.net_hist),
            }


DEMO_SPOT = (38.30, -4.20)   # punto aislado de Sierra Morena donde se "detiene" el tren de la demo
DEMO_LINES = [(40.40, -3.69, 37.88, -4.79), (40.40, -3.69, 41.38, 2.14), (40.40, -3.69, 39.47, -0.38),
              (41.65, -0.88, 41.38, 2.14), (37.39, -5.98, 36.72, -4.42), (42.88, -8.54, 40.97, -5.66),
              (43.26, -2.93, 41.65, -0.88), (39.47, -0.38, 38.35, -0.48)]


def demo_feed(now):
    """Feed simulado (mismo formato que el real): flota en movimiento + un tren parado + otro que se le acerca."""
    base = {"codEstAnt": "60000", "codEstSig": "50500", "codOrigen": "60000", "codDestino": "50500",
            "horaLlegadaSigEst": "", "accesible": False, "time": int(now) - 3}
    trenes = []
    for i in range(36):
        la1, lo1, la2, lo2 = DEMO_LINES[i % len(DEMO_LINES)]
        v = 55.0 if i % 3 else 30.0
        f = (i * 0.137 + v * now / max(1.0, haversine(la1, lo1, la2, lo2))) % 1.0
        trenes.append(dict(base, codComercial=f"D{i:03d}", codProduct=2 if i % 3 else 16,
                           latitud=la1 + (la2 - la1) * f, longitud=lo1 + (lo2 - lo1) * f,
                           ultRetraso=str((i * 7) % 48 - 3), mat=f"9{i:05d}", accesible=bool(i % 2)))
    la0, lo0 = DEMO_SPOT
    trenes.append(dict(base, codComercial="DEMO-P", codProduct=11, latitud=la0, longitud=lo0, ultRetraso="22", mat="900001"))
    off = 55.0 * (now % 140) - 8000.0   # el tren DEMO-A recorre 7,7 km hacia el parado cada 140 s
    trenes.append(dict(base, codComercial="DEMO-A", codProduct=2, latitud=la0 + off / 110540.0, longitud=lo0,
                       ultRetraso="0", mat="900002"))
    return {"fechaActualizacion": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "trenes": trenes}


@st.cache_resource
def get_demo_monitor(version=MONITOR_VERSION):
    mon = Monitor(demo=True)
    mon.start()
    return mon


@st.cache_resource
def get_monitor(version=MONITOR_VERSION):
    mon = Monitor()
    mon.update_channels(read_channel_defaults())
    mon.start()
    return mon


# ==========================================
# 8. Alarma en el navegador: pitidos, SIRENA continua, voz y notificaciones
# ==========================================
# El audio vive en la ventana PADRE de Streamlit y se desbloquea con cualquier clic/tecla.
# La sirena (dos tipos) suena en bucle hasta que se llama a setSiren(null) (botón RECONOCER).
BRIDGE_JS = """
(function(){
var P; try { P = window.parent; void P.document; } catch(e) { P = window; }
if (P.__ebmAlarm && P.__ebmAlarm.v === 4) return;
if (P.__ebmAlarm && P.__ebmAlarm._stop) { try { P.__ebmAlarm._stop(); } catch(e) {} }
var A = {v:4, ctx:null, askedNotif:false, voiceUnlocked:false, flash:null, flashText:null, base:null,
         want:null, sirenKind:null, sirenNodes:null};
A.unlock = function(){
  try {
    var C = P.AudioContext || P.webkitAudioContext;
    if (C && !A.ctx) { A.ctx = new C(); }
    if (A.ctx && A.ctx.state === 'suspended') {
      var p = A.ctx.resume(); if (p && p.then) p.then(function(){ if (A.want) A._start(); });
    }
    if (A.ctx) {
      var o = A.ctx.createOscillator(), g = A.ctx.createGain();
      g.gain.value = 0.0001; o.connect(g); g.connect(A.ctx.destination);
      o.start(); o.stop(A.ctx.currentTime + 0.03);
    }
    if (A.want) { setTimeout(function(){ A._start(); }, 60); }
    if (P.speechSynthesis && !A.voiceUnlocked) {
      var u = new P.SpeechSynthesisUtterance(' '); u.volume = 0; P.speechSynthesis.speak(u); A.voiceUnlocked = true;
    }
    if (P.Notification && P.Notification.permission === 'default' && !A.askedNotif) {
      A.askedNotif = true; P.Notification.requestPermission();
    }
  } catch(e) {}
};
['pointerdown','keydown','touchstart','click'].forEach(function(ev){
  P.document.addEventListener(ev, A.unlock, true);
});
A.tone = function(f, at, dur, vol){
  var c = A.ctx, t0 = c.currentTime + at;
  var o = c.createOscillator(), g = c.createGain();
  o.type = 'square'; o.frequency.setValueAtTime(f, t0);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(vol, t0 + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0 + dur + 0.05);
};
A.freqs = {accident:[1000,1600], early:[600,600], brake:[700,950], stopped:[800,1000], risk:[950,1400], system:[500,500]};
A.play = function(kind, beeps){
  if (!A.ctx || !beeps) return false;
  if (A.ctx.state === 'suspended') { try { A.ctx.resume(); } catch(e) {} }
  var f = A.freqs[kind] || [800];
  for (var i = 0; i < beeps; i++) { A.tone(f[i % f.length], i * 0.32, 0.24, 0.5); }
  return A.ctx.state === 'running';
};
// ---- Sirena continua: 'wail' (barrido lento, detenido) y 'hilo' (dos tonos alternos, riesgo) ----
A._stop = function(){
  if (A.sirenNodes) {
    A.sirenNodes.forEach(function(n){
      try { if (n.stop) n.stop(); } catch(e) {}
      try { n.disconnect(); } catch(e) {}
    });
    A.sirenNodes = null;
  }
  A.sirenKind = null;
};
A._start = function(){
  var kind = A.want;
  if (!kind || !A.ctx || A.ctx.state !== 'running') return false;
  if (A.sirenKind === kind) return true;
  A._stop();
  var c = A.ctx, t0 = c.currentTime;
  var osc = c.createOscillator(), lfo = c.createOscillator(), depth = c.createGain(), amp = c.createGain();
  if (kind === 'hilo') {
    osc.type = 'square'; osc.frequency.value = 860;
    lfo.type = 'square'; lfo.frequency.value = 1.7; depth.gain.value = 150;   // 710 Hz <-> 1010 Hz
  } else {
    osc.type = 'sawtooth'; osc.frequency.value = 950;
    lfo.type = 'sine'; lfo.frequency.value = 0.45; depth.gain.value = 380;    // barrido 570 - 1330 Hz
  }
  amp.gain.setValueAtTime(0.0001, t0);
  amp.gain.exponentialRampToValueAtTime(0.5, t0 + 0.15);
  lfo.connect(depth); depth.connect(osc.frequency); osc.connect(amp); amp.connect(c.destination);
  osc.start(); lfo.start();
  A.sirenNodes = [osc, lfo, depth, amp]; A.sirenKind = kind;
  return true;
};
A._stopFlash = function(){
  try {
    if (A.flash) { P.clearInterval(A.flash); A.flash = null; }
    if (A.base) { P.document.title = A.base; }
    A.flashText = null;
  } catch(e) {}
};
A.flashTitle = function(text, forever){
  try {
    var d = P.document; if (!A.base) A.base = d.title;
    if (forever && A.flash && A.flashText === text) return;
    if (A.flash) P.clearInterval(A.flash);
    A.flashText = text; var n = 0;
    A.flash = P.setInterval(function(){
      d.title = (n % 2 === 0) ? text : A.base; n++;
      if (!forever && n > 20) { P.clearInterval(A.flash); A.flash = null; d.title = A.base; }
    }, 900);
  } catch(e) {}
};
A.setSiren = function(kind, title){
  A.want = kind || null;
  if (!kind) { A._stop(); A._stopFlash(); return; }
  if (A.ctx && A.ctx.state === 'suspended') {
    try { var p = A.ctx.resume(); if (p && p.then) p.then(function(){ A._start(); }); } catch(e) {}
  }
  A._start();
  try { if (P.navigator.vibrate) P.navigator.vibrate([400,150,400,150,800]); } catch(e) {}
  if (title) A.flashTitle(title, true);
};
A.fire = function(o){
  var evs = o.events || []; if (!evs.length) return;
  var top = evs[0];
  evs.forEach(function(e){ if ((e.rank || 0) > (top.rank || 0)) top = e; });
  if (o.sound && top.beeps && !A.want) {
    try { A.play(top.kind, top.beeps); } catch(e) {}
    try {
      if (P.speechSynthesis && top.speak) {
        P.setTimeout(function(){
          var u = new P.SpeechSynthesisUtterance(top.speak); u.lang = 'es-ES'; u.rate = 1.05;
          P.speechSynthesis.cancel(); P.speechSynthesis.speak(u);
        }, 1100);
      }
    } catch(e) {}
    try { if (P.navigator.vibrate) P.navigator.vibrate([200,100,200,100,400]); } catch(e) {}
  }
  try {
    if (P.Notification && P.Notification.permission === 'granted') {
      evs.slice(0, 3).forEach(function(e){
        new P.Notification(e.title, {body: e.body, tag: e.tag, requireInteraction: (e.kind === 'risk')});
      });
    }
  } catch(e) {}
  if (!A.want) A.flashTitle(top.title, false);
};
A.sync = function(o){
  if (o.events && o.events.length) A.fire(o);
  A.setSiren(o.siren || null, o.sirenTitle || '');
};
P.__ebmAlarm = A;
})();
"""

STATUS_HTML = """
<div id="s" style="font:12px 'Courier New',monospace;color:#7d8da0;padding:4px 0;"></div>
<script>
(function(){
var P = null; try { P = window.parent; void P.document; } catch(e) { P = null; }
function upd(){
  var el = document.getElementById('s');
  if (!P) { el.innerHTML = '⚠ AUDIO: <b style="color:#ff6b6b">puente no disponible</b> — activa «Sonido de respaldo»'; return; }
  var A = P.__ebmAlarm;
  var st = (A && A.ctx) ? A.ctx.state : 'sin-desbloquear';
  var n = (P.Notification) ? P.Notification.permission : 'n/d';
  var ok = (st === 'running');
  var sir = (A && A.sirenKind) ? ('<b style="color:#ff5a5a">SIRENA ' + A.sirenKind.toUpperCase() + '</b>') : 'sirena en reposo';
  el.innerHTML = '🔈 AUDIO: <b style="color:' + (ok ? '#39ff88' : '#ffb000') + '">' +
    (ok ? 'LISTO' : 'haz clic en la página para desbloquear') + '</b> · NOTIF: <b>' + n + '</b> · ' + sir;
}
upd(); setInterval(upd, 1000);
})();
</script>
"""


def _event_payload(ev):
    lvl = LEVELS[ev["kind"]]
    return {"kind": ev["kind"], "rank": lvl["rank"], "beeps": lvl["beeps"],
            "title": f"{lvl['icon']} {lvl['label']}", "body": ev["msg"],
            "tag": ev.get("key", "renfe"), "speak": ev.get("speak") or ev["msg"]}


def browser_sync(events, sound, siren_kind, siren_title, token):
    """Una sola llamada por ejecución: instala el puente, dispara eventos y sincroniza la sirena."""
    payload = {"sound": bool(sound), "events": [_event_payload(e) for e in events],
               "siren": ("hilo" if siren_kind == "risk" else "wail") if siren_kind else None,
               "sirenTitle": siren_title}
    data = json.dumps(payload).replace("</", "<\\/")
    code = (f"<!-- {token} --><script>{BRIDGE_JS}\n"
            "(function(){var P;try{P=window.parent;void P.document;}catch(e){P=window;}"
            f"if(P.__ebmAlarm){{P.__ebmAlarm.sync({data});}}}})();</script>")
    return render_html(code, height=0)


def _build_wav(kind, loop_seconds=4.0):
    """Sirena de respaldo en WAV (bucle de 4 s) por si el puente JS no funciona."""
    sr = 16000
    t = np.arange(int(sr * loop_seconds)) / sr
    if kind == "risk":
        f = 860 + 150 * np.sign(np.sin(2 * np.pi * 1.7 * t))
        phase = 2 * np.pi * np.cumsum(f) / sr
        wave_ = np.sign(np.sin(phase))
    else:
        f = 950 + 380 * np.sin(2 * np.pi * 0.5 * t)
        phase = 2 * np.pi * np.cumsum(f) / sr
        wave_ = 2 * ((phase / (2 * np.pi)) % 1) - 1
    pcm = (wave_ * 32767 * 0.5).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def make_siren_wav(kind):
    return _build_wav(kind)


def play_backup_siren(kind):
    """Reproductor nativo en bucle; solo existe en pantalla mientras la sirena está activa."""
    wav = make_siren_wav(kind)
    for kwargs in ({"autoplay": True, "loop": True}, {"autoplay": True}, {}):
        try:
            st.audio(wav, format="audio/wav", **kwargs)
            return
        except TypeError:
            continue


# ==========================================
# 9. Estado de sirena (por pestaña) y mapa
# ==========================================
def arm_siren(kind_event, msg, test=False):
    """Arma la sirena si el nivel pedido es mayor que el de la que ya suena."""
    ss = st.session_state
    rank = LEVELS[kind_event]["rank"]
    cur = ss.get("siren")
    if cur and cur["rank"] >= rank:
        return
    ss.siren = {"rank": rank, "kind": "risk" if rank >= 4 else "stopped", "msg": msg, "since": time.time(),
                "label": LEVELS[kind_event]["label"], "test": test}
    ss.siren_ver = ss.get("siren_ver", 0) + 1


def ack_siren():
    ss = st.session_state
    ss.siren = None
    ss.siren_ver = ss.get("siren_ver", 0) + 1


def test_siren():
    arm_siren("risk", "PRUEBA DE SIRENA: pulsa RECONOCER para silenciarla.", test=True)


def color_retraso(minutos, is_stopped, is_suspect=False):
    if is_stopped:
        return "#ff3232"
    if is_suspect:
        return "#ff9f1a"
    if minutos <= 5:
        return "#2ecc71"
    if minutos <= 15:
        return "#f1c40f"
    if minutos <= 30:
        return "#e67e22"
    return "#e74c3c"


def find_clicked_train(df_f, map_data):
    if df_f.empty or not map_data:
        return None
    tip = map_data.get("last_object_clicked_tooltip")
    if tip:
        cod = str(tip).split(" · ")[0].strip()
        match = df_f[df_f["cod_comercial"] == cod]
        if not match.empty:
            return match.iloc[0]
    clicked = map_data.get("last_object_clicked")
    if clicked:
        lat, lon = clicked.get("lat"), clicked.get("lng")
        if lat is not None and lon is not None:
            k = math.cos(math.radians(lat))
            d = (df_f["lat"] - lat) ** 2 + ((df_f["lon"] - lon) * k) ** 2
            return df_f.loc[d.idxmin()]
    return None


def ann(label, value, state):
    return f'<div class="ann {state}"><span class="lamp"></span>{esc(label)}<i>{esc(value)}</i></div>'


def mmss(seconds):
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


PUSH_LEVELS = {"🟡 Aviso temprano y superiores (todo)": 1, "🟠 Frenada brusca y superiores": 2,
               "🔴 Detenido en vía y superiores": 3, "🚨 Solo riesgo crítico": 4}
SIREN_LEVELS = {"🔴 Detenido en vía y superiores": 3, "🚨 Solo riesgo crítico": 4,
                "🟠 Frenada brusca y superiores": 2, "🟡 Todo (aviso temprano)": 1}


# ==========================================
# 10. Interfaz principal
# ==========================================
def _carto_key():
    try:
        v = st.secrets.get("CARTO_API_KEY")
    except Exception:  # noqa: BLE001
        v = None
    return str(v or os.getenv("CARTO_API_KEY") or "TU_API_KEY").strip()


CARTO_KEY = _carto_key()
_ATTR_CARTO = '&copy; <a href="https://carto.com/attributions">CARTO</a> &copy; OpenStreetMap contributors'
# tema -> (url de tiles, atribución, color de fondo mientras cargan). Claro = fondo blanco por defecto.
TILES = {
    "Claro": (f"https://basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png?key={CARTO_KEY}", _ATTR_CARTO, "#ffffff"),
    "Oscuro": (f"https://basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png?key={CARTO_KEY}", _ATTR_CARTO, "#0b0f14"),
    "OSM": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "&copy; OpenStreetMap contributors", "#ffffff"),
}
KIND_COLOR = {"accident": "#ff0000", "risk": "#ff2d8a", "stopped": "#ff9f1a", "brake": "#bd5fff"}
TRACK_TRAINS = "Trenes"


def _mon():
    return get_demo_monitor(MONITOR_VERSION) if st.session_state.get("demo_mode") else get_monitor(MONITOR_VERSION)


def cb_focus(lat, lon, zoom=11):
    ss = st.session_state
    ss.focus = (float(lat), float(lon), int(zoom))
    ss.view_nonce = ss.get("view_nonce", 0) + 1


def cb_reset_view():
    ss = st.session_state
    ss.focus = None
    ss.view_nonce = ss.get("view_nonce", 0) + 1


def cb_zoom(delta):
    ss = st.session_state
    lat, lon, z = ss.focus if ss.get("focus") else (40.0, -3.5, 6)
    ss.focus = (lat, lon, max(4, min(17, int(z) + int(delta))))
    ss.view_nonce = ss.get("view_nonce", 0) + 1


def cb_retry_stations():
    mon = _mon()
    mon.stations_try_ts = 0.0
    mon.poll_now()
    st.toast("Reintentando la descarga de estaciones…", icon="🏁")


def cb_refresh():
    _mon().poll_now()
    st.toast("Actualizando datos de Renfe…", icon="🔄")


def cb_confirm(cod):
    ok = _mon().confirm_accident(cod)
    st.toast(f"Accidente del tren {cod} confirmado y tramo cortado." if ok else "No se pudo confirmar.",
             icon="💥" if ok else "⚠")


def cb_dismiss(cod):
    _mon().dismiss_accident(cod)
    st.toast(f"Tren {cod} marcado como falsa alarma; se reabre su tramo.", icon="✅")


def cb_cut_train(cod):
    name = _mon().cut_from_train(cod)
    st.toast(f"Tramo cortado: {name}" if name else "No se pudo cortar el tramo.", icon="🚧")


def cb_reopen(cut_id):
    _mon().close_cut(cut_id)
    st.toast("Tramo reabierto.", icon="✅")


def fmt_dur(seconds):
    s = max(0, int(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else mmss(s)


def count_kind(hist_df, kind, secs):
    if hist_df.empty:
        return 0
    m = (hist_df["kind"] == kind) & (hist_df["first_ts"] >= time.time() - secs)
    if kind == "accident":
        m &= hist_df["confirmed"] != -1
    return int(m.sum())


def make_base_map(theme, center, zoom):
    """Un único mapa base fijo (sin selector interno): así no cambia de color al refrescar."""
    url, attr, bg = TILES.get(theme, TILES["Claro"])
    m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True)
    folium.TileLayer(tiles=url, attr=attr, name="Mapa base", control=False, max_zoom=19).add_to(m)
    m.get_root().header.add_child(folium.Element(f"<style>.leaflet-container{{background:{bg} !important;}}</style>"))
    return m


def add_cuts(m, cuts):
    for c in cuts:
        pts = [list(p) for p in c["pts"]]
        if len(pts) < 2:
            continue
        origen = {"auto": "automático (posible accidente)", "manual": "manual", "adif": "Adif"}.get(c.get("source"), "")
        pop = f"<b>🚧 {esc(c['name'])}</b><br>Origen: {origen}<br>{esc(c.get('note', ''))}"
        folium.PolyLine(pts, color="#ff2d2d", weight=14, opacity=0.28).add_to(m)
        folium.PolyLine(pts, color="#ff2d2d", weight=4, dash_array="9 7", tooltip=f"🚧 {c['name']}",
                        popup=folium.Popup(pop, max_width=300)).add_to(m)
        i = (len(pts) - 1) // 2
        mid = [(pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2]
        folium.Marker(mid, tooltip=f"🚧 {c['name']}", icon=folium.DivIcon(
            icon_size=(0, 0), icon_anchor=(0, 0), html=(
                '<div style="position:absolute;left:-11px;top:-11px;width:22px;height:22px;background:#ff2d2d;'
                'border:2px solid #fff;transform:rotate(45deg);box-shadow:0 0 0 4px rgba(255,45,45,.35)"></div>'
                '<div style="position:absolute;left:18px;top:-10px;white-space:nowrap;background:#ff2d2d;color:#fff;'
                f'font:700 11px Arial;padding:2px 6px;border-radius:3px">TRAMO CORTADO · {esc(c["name"])[:42]}</div>'))
        ).add_to(m)


def add_history(m, hist_df):
    for r in hist_df.to_dict("records"):
        if pd.isna(r["lat"]) or pd.isna(r["lon"]):
            continue
        col = KIND_COLOR.get(r["kind"], "#888")
        folium.CircleMarker(
            [r["lat"], r["lon"]], radius=4 + 2 * int(r["severity"] or 1), color=col, weight=1, fill=True,
            fill_color=col, fill_opacity=0.35,
            tooltip=f"{LEVELS[r['kind']]['label']} · {r['ref']} · {fmt_clock(r['first_ts'], '%d/%m %H:%M')}").add_to(m)


def add_trains(m, df_f, info, sel_cod, acc_cods, scores, usar_cluster, stale_s=600):
    cluster = MarkerCluster(name=TRACK_TRAINS).add_to(m) if usar_cluster else None
    labels = 0
    for _, row in df_f.iterrows():
        cod = row["cod_comercial"]
        is_stopped, is_suspect, is_braking = bool(row["is_stopped"]), bool(row["is_suspect"]), bool(row["braking"])
        is_acc = cod in acc_cods
        stale = pd.notna(row["gps_age_s"]) and row["gps_age_s"] > stale_s
        color = "#8b949e" if stale else ("#ff0000" if is_acc else color_retraso(row["retraso_min"], is_stopped, is_suspect))
        radius = 14 if is_acc else (12 if is_stopped else (9 if is_suspect else 6))
        estado = "SIN SEÑAL GPS" if stale else "POSIBLE ACCIDENTE" if is_acc else "DETENIDO" if is_stopped else \
            ("AVISO TEMPRANO" if is_suspect else "En marcha")
        parado = f"Baja velocidad desde hace: {int(row['stopped_for_s'])} s<br>" if row["stopped_for_s"] > 0 else ""
        freno = "<b style='color:#bd5fff;'>Frenada brusca reciente</b><br>" if is_braking else ""
        sc = scores.get(cod, {}).get("score", 0)
        gps = f"GPS hace {int(row['gps_age_s'])} s<br>" if pd.notna(row["gps_age_s"]) else ""
        pop = (f"<div style=\"font-family:Arial;background:#161b22;color:white;padding:10px;border-radius:8px;min-width:210px;\">"
               f"<b>🚆 {esc(cod)}</b> · {esc(row['tipo'])}<br>"
               f"{esc(label_est(row['origen'], info))} → {esc(label_est(row['destino'], info))}<br>"
               f"<span style=\"color:{color};font-weight:bold;\">Estado: {estado}</span><br>"
               f"Velocidad: {row['speed_kmh']} km/h · Rumbo {round(row['heading'])}°<br>{parado}{freno}{gps}"
               f"Retraso: {fmt_delay(row['retraso_min'])} · Riesgo {sc}/100<br>Matrícula: {esc(row['mat'])}</div>")
        marker = folium.CircleMarker(
            location=[row["lat"], row["lon"]], radius=radius, color=color, fill=True, fill_color=color,
            fill_opacity=0.9, weight=2, popup=folium.Popup(pop, max_width=300),
            tooltip=f"{cod} · {row['speed_kmh']} km/h")
        if cluster is not None and not (is_stopped or is_suspect or is_braking):
            marker.add_to(cluster)
        else:
            marker.add_to(m)
        if is_acc:
            folium.CircleMarker([row["lat"], row["lon"]], radius=24, color="#ff0000", fill=False, weight=3,
                                dash_array="4 4").add_to(m)
        if is_braking:
            folium.CircleMarker([row["lat"], row["lon"]], radius=17, color="#bd5fff", fill=False, weight=3).add_to(m)
        if sel_cod == cod:
            folium.CircleMarker([row["lat"], row["lon"]], radius=21, color="#0a84ff", fill=False, weight=3).add_to(m)
        if (row["retraso_min"] >= 15 or is_stopped or is_suspect) and labels < 70:
            labels += 1
            txt = esc(cod) + (f" +{int(row['retraso_min'])}" if row["retraso_min"] >= 1 else "")
            folium.Marker(
                [row["lat"], row["lon"]], icon=folium.DivIcon(icon_size=(0, 0), icon_anchor=(-10, 10), html=(
                    f'<div style="background:#0F171F;border:1.5px solid {color};color:#fff;font:11px Consolas,monospace;'
                    f'padding:1px 5px;white-space:nowrap;display:inline-block;">{txt}</div>'))).add_to(m)


def main():
    ss = st.session_state
    st_autorefresh(interval=int(ss.get("refresh_s", DEFAULT_REFRESH_S)) * 1000, key="refresh")
    ss.setdefault("audio_ready", False)
    ss.setdefault("siren", None)
    ss.setdefault("siren_ver", 0)
    ss.setdefault("view_nonce", 0)
    ss.setdefault("focus", None)
    stretch = stretch_kwargs(st.button)

    # --- Monitor y primer dato ---
    demo = bool(ss.get("demo_mode", False))
    mon = _mon()
    mon.ensure_running()
    if ss.get("mon_id") != id(mon):  # al cambiar real <-> demo se reinicia el seguimiento de eventos y la sirena
        ss.mon_id = id(mon)
        ss.pop("last_seq", None)
        ss.siren = None
        ss.siren_ver = ss.get("siren_ver", 0) + 1
    if not mon.has_stations():
        mon.set_stations(load_stations() or load_stations_cache())
    snap = mon.snapshot()
    if snap is None:
        if demo:
            mon.tick()
        else:
            raw, ts, _ = load_feed()
            if raw:
                mon.ingest(raw, ts)
        snap = mon.snapshot()
    if snap is None:
        st.error("❌ Todavía no hay datos de trenes.")
        st.caption(f"Monitor: {'activo' if mon.thread and mon.thread.is_alive() else 'detenido'} · fallos seguidos: "
                   f"{mon.consecutive_errors} · último error: {mon.last_error_detail or mon.last_error or 'ninguno'}")
        d1, d2, d3 = st.columns(3)
        d1.button("🔄 Reintentar", key="err_retry", on_click=cb_refresh, **stretch)
        d3.checkbox("🧪 Modo demo (sin conexión)", key="demo_mode")
        if d2.button("🩺 Probar conexión", key="err_diag", **stretch):
            for nombre, ok, detalle in diagnose_connection():
                (st.success if ok else st.error)(f"{nombre}: {detalle}")
            st.caption("Si ves HTTP 403/429 el servidor está limitando tu IP; si ves ConnectionError o Timeout, "
                       "es tu red, firewall, VPN o proxy.")
        return

    top = st.container()
    alarm_zone = st.container()
    main_zone = st.container()
    bottom = st.container()

    # ================= PARTE INFERIOR (se rellena primero: los parámetros alimentan todo) =================
    with bottom:
        t_par, t_cut, t_acc, t_tel, t_can, t_inc, t_reg, t_sis = st.tabs(
            ["⚙ PARÁMETROS", "🚧 TRAMOS CORTADOS", "💥 ACCIDENTES (30 d)", "📊 TELEMETRÍA", "📡 CANALES",
             "🛰 INCIDENCIAS ADIF", "📜 REGISTRO", "🩺 SISTEMA"])

        with t_par:
            p1, p2, p3 = st.columns(3)
            with p1:
                early_stop_s = st.slider("Aviso temprano tras (s a baja velocidad)", 10, 180, DEFAULT_CFG["early_stop_s"], 5)
                min_stop_s = st.slider("Detenido confirmado tras (s)", 20, 300, DEFAULT_CFG["min_stop_s"], 10)
                station_radius_m = st.slider("Distancia mínima a estación (m)", 200, 3000, DEFAULT_CFG["station_radius_m"], 100)
                if early_stop_s >= min_stop_s:
                    st.caption("⚠ El aviso temprano debe ser menor que el tiempo de detenido confirmado.")
                accident_s = st.slider("Posible accidente: detenido (s) lejos de estación", 60, 900, DEFAULT_CFG["accident_s"], 30)
            with p2:
                risk_dist_m = st.slider("Distancia de riesgo (m)", 1000, 15000, DEFAULT_CFG["risk_dist_m"], 500)
                risk_ttc_s = st.slider("Tiempo hasta contacto máx. (s)", 30, 600, DEFAULT_CFG["risk_ttc_s"], 10)
                risk_heading_deg = st.slider("Tolerancia de rumbo (°)", 15, 90, DEFAULT_CFG["risk_heading_deg"], 5)
                risk_min_kmh = st.slider("Velocidad mínima en marcha (km/h)", 10, 200, DEFAULT_CFG["risk_min_kmh"], 5)
            with p3:
                brake_min_kmh = st.slider("Frenada brusca: velocidad previa mín. (km/h)", 40, 300, DEFAULT_CFG["brake_min_kmh"], 10)
                brake_ms2 = st.slider("Frenada brusca: deceleración (m/s²)", 0.4, 2.0, float(DEFAULT_CFG["brake_ms2"]), 0.1)
                cut_half_km = st.slider("Tramo cortado automático: ± km alrededor del tren", 1, 50, DEFAULT_CFG["cut_half_km"], 1)
                cut_warn_m = st.slider("Aviso a trenes que se acercan a un tramo cortado (m)", 2000, 30000, DEFAULT_CFG["cut_warn_m"], 1000)
                risk_include_suspect = st.checkbox("Riesgo también contra trenes con aviso temprano",
                                                   value=DEFAULT_CFG["risk_include_suspect"])
            q1, q2, q3 = st.columns(3)
            with q1:
                st.slider("Refresco de la interfaz (s)", 5, 60, DEFAULT_REFRESH_S, 5, key="refresh_s")
            with q2:
                poll_s = st.slider("Sondeo del monitor (s)", 3, 60, DEFAULT_POLL_S, 1)
            with q3:
                st.selectbox("🚨 Sirena continua desde el nivel", list(SIREN_LEVELS.keys()), index=0, key="siren_label")
            cfg = {"early_stop_s": early_stop_s, "min_stop_s": min_stop_s, "station_radius_m": station_radius_m,
                   "risk_dist_m": risk_dist_m, "risk_ttc_s": risk_ttc_s, "risk_heading_deg": risk_heading_deg,
                   "risk_min_kmh": risk_min_kmh, "risk_include_suspect": risk_include_suspect,
                   "brake_min_kmh": brake_min_kmh, "brake_ms2": brake_ms2, "accident_s": accident_s,
                   "cut_half_km": cut_half_km, "cut_warn_m": cut_warn_m}

        with t_can:
            st.caption("Los avisos salen desde el monitor en segundo plano, aunque no haya ninguna pestaña abierta. "
                       "Mejor con variables de entorno o st.secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NTFY_TOPIC, "
                       "NTFY_SERVER, ALERT_WEBHOOK_URL, ADIF_INCIDENTS_URL); los campos de aquí solo viven en memoria.")
            c1, c2 = st.columns(2)
            with c1:
                tg_token = st.text_input("Telegram · bot token", type="password", key="ui_tg_token")
                tg_chat = st.text_input("Telegram · chat id", key="ui_tg_chat")
                adif_url = st.text_input("Adif · URL JSON de incidencias", key="ui_adif")
            with c2:
                ntfy_topic = st.text_input("ntfy · topic", key="ui_ntfy_topic")
                ntfy_server = st.text_input("ntfy · servidor", value="https://ntfy.sh", key="ui_ntfy_server")
                webhook = st.text_input("Webhook · URL (JSON)", type="password", key="ui_webhook")
            push_label = st.selectbox("Enviar avisos desde el nivel", list(PUSH_LEVELS.keys()), index=0)
            cfg["push_min_rank"] = PUSH_LEVELS[push_label]
            mon.update_channels({"telegram_token": tg_token, "telegram_chat": tg_chat, "ntfy_topic": ntfy_topic,
                                 "ntfy_server": ntfy_server if ntfy_topic else "", "webhook_url": webhook,
                                 "adif_url": adif_url})
            if st.button("📨 Enviar mensaje de prueba a los canales", key="btn_test_channels"):
                if not mon.channel_names():
                    st.warning("No hay ningún canal configurado.")
                else:
                    for canal, ok, detalle in mon.send_test():
                        (st.success if ok else st.error)(f"{canal}: {'enviado' if ok else 'falló'} ({detalle})")
            entregas = mon.recent_deliveries()
            if entregas:
                st.caption("Últimos envíos")
                st.dataframe(pd.DataFrame(entregas), hide_index=True)

    mon.set_cfg(cfg)
    mon.set_poll(poll_s)
    snap = mon.snapshot() or snap
    df = snap["df"]
    info = snap["info"]
    full_cfg = {**DEFAULT_CFG, **cfg}
    try:
        an = analyze(df, full_cfg, snap["cuts"], snap["dismissed"])
    except Exception as e:  # noqa: BLE001 - un fallo de análisis no puede dejar el mapa vacío
        st.error(f"Fallo en el análisis de riesgo ({type(e).__name__}); se muestran los trenes sin indicadores.")
        an = {"risk": [], "acc": [], "cut": [], "scores": {}}
    risk_alerts, cut_alerts, acc, scores = an["risk"], an["cut"], an["acc"], an["scores"]
    acc_cods = {a["cod"] for a in acc}
    hist_df = db_incidents(RETENTION_DAYS) if snap["db_ok"] else pd.DataFrame(columns=INC_COLUMNS)
    siren_rank = SIREN_LEVELS[ss.get("siren_label", list(SIREN_LEVELS.keys())[0])]
    sound_on = bool(ss.audio_ready and not ss.get("mute", False))
    now = time.time()

    # ================= PESTAÑAS INFERIORES: tramos, accidentes, telemetría, adif, registro, sistema =================
    with bottom:
        with t_cut:
            cl, cr = st.columns([1.3, 1])
            with cl:
                st.markdown("**Tramos cortados activos** (se dibujan en el mapa y avisan a los trenes que se acercan)")
                if not snap["cuts"]:
                    st.caption("Ninguno. Se crean solos ante un posible accidente, o a mano desde aquí o desde la ficha del tren.")
                for c in snap["cuts"]:
                    since = fmt_clock(c["created_ts"], "%d/%m %H:%M") if c.get("created_ts") else ""
                    exp = f" · caduca {fmt_clock(c['expires_ts'], '%d/%m %H:%M')}" if c.get("expires_ts") else ""
                    r1, r2 = st.columns([4, 1])
                    with r1:
                        st.markdown(f'<div class="cutrow"><b>🚧 {esc(c["name"])}</b><small>{esc(c.get("source", ""))} · '
                                    f'desde {since}{exp} · {len(c["pts"])} puntos</small><small>{esc(c.get("note", ""))}</small></div>',
                                    unsafe_allow_html=True)
                    with r2:
                        if c.get("source") != "adif":
                            st.button("Reabrir", key=f"reopen_{c['id']}", on_click=cb_reopen, args=(c["id"],), **stretch)
            with cr:
                st.markdown("**Cerrar un tramo a mano**")
                est_opts = {f"{label_est(code, info)} · {code}": (s["lat"], s["lon"]) for code, s in info.items()}
                with st.form("form_cut", clear_on_submit=True):
                    name = st.text_input("Nombre / motivo", placeholder="Madrid – Córdoba por accidente")
                    sel_est = st.multiselect("Estaciones del tramo, en orden", sorted(est_opts))
                    coords = st.text_area("…o puntos lat,lon separados por «;»", height=68,
                                          placeholder="38.02,-4.52; 38.20,-4.40")
                    dur = st.selectbox("Duración", ["Hasta reabrirlo", "6 horas", "24 horas", "7 días"])
                    ok = st.form_submit_button("🚧 Cerrar tramo", type="primary")
                if ok:
                    pts = [est_opts[k] for k in sel_est] + parse_latlon_list(coords)
                    hours = {"Hasta reabrirlo": None, "6 horas": 6, "24 horas": 24, "7 días": 168}[dur]
                    if len(pts) < 2:
                        st.error("Hacen falta al menos 2 puntos (estaciones o coordenadas).")
                    elif mon.add_cut(name or "Tramo cortado", pts, hours, "Cierre manual"):
                        st.success("Tramo cerrado y visible en el mapa.")
                        st.rerun()
                    else:
                        st.error("No se pudo guardar (¿SQLite disponible?).")
                st.caption("Con estaciones intermedias el trazo sigue mejor la línea. No tengo el trazado real de la vía: "
                           "el dibujo une los puntos en línea recta.")

        with t_acc:
            a24, a7, a30 = count_kind(hist_df, "accident", 86400), count_kind(hist_df, "accident", 7 * 86400), \
                count_kind(hist_df, "accident", 30 * 86400)
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Posibles accidentes 24 h", a24)
            k2.metric("7 días", a7)
            k3.metric("30 días", a30)
            k4.metric("Detenciones 30 d", count_kind(hist_df, "stopped", 30 * 86400))
            k5.metric("Riesgos 30 d", count_kind(hist_df, "risk", 30 * 86400))
            if hist_df.empty:
                st.caption("Sin incidentes registrados todavía. Se guardan 30 días en SQLite aunque se cierre la aplicación.")
            else:
                d = hist_df.copy()
                d["dia"] = pd.to_datetime(d["first_ts"], unit="s").dt.strftime("%m-%d")
                st.bar_chart(d.groupby(["dia", "kind"]).size().unstack(fill_value=0))
                rows = []
                for r in hist_df.to_dict("records"):
                    end = r["resolved_ts"] if pd.notna(r["resolved_ts"]) else now
                    estado = "CONFIRMADO" if r["confirmed"] == 1 else "FALSA ALARMA" if r["confirmed"] == -1 else \
                        ("Resuelto" if pd.notna(r["resolved_ts"]) else "ACTIVO")
                    rows.append({"Inicio": fmt_clock(r["first_ts"], "%d/%m %H:%M"), "Tipo": LEVELS[r["kind"]]["label"],
                                 "Ref.": r["ref"], "Duración": fmt_dur(end - r["first_ts"]), "Estado": estado,
                                 "Detalle": r["msg"]})
                tabla = pd.DataFrame(rows)
                st.dataframe(tabla, hide_index=True)
                st.download_button("⬇ Descargar historial (CSV)", tabla.to_csv(index=False).encode("utf-8"),
                                   file_name="ebm_incidentes_30d.csv", mime="text/csv", key="dl_inc")
                abiertos = hist_df[(hist_df["kind"] == "accident") & hist_df["resolved_ts"].isna()]
                if not abiertos.empty:
                    st.markdown("**Accidentes abiertos**")
                    for r in abiertos.to_dict("records"):
                        x1, x2, x3, x4 = st.columns([3, 1, 1, 1])
                        x1.markdown(f"💥 Tren **{esc(r['ref'])}** · desde {fmt_clock(r['first_ts'], '%H:%M:%S')}")
                        x2.button("Confirmar", key=f"c_{r['id']}", on_click=cb_confirm, args=(r["ref"],), **stretch)
                        x3.button("Falsa alarma", key=f"d_{r['id']}", on_click=cb_dismiss, args=(r["ref"],), **stretch)
                        if pd.notna(r["lat"]):
                            x4.button("Centrar", key=f"f_{r['id']}", on_click=cb_focus, args=(r["lat"], r["lon"], 11), **stretch)

        with t_tel:
            gps_num = pd.to_numeric(df["gps_age_s"], errors="coerce") if not df.empty else pd.Series(dtype=float)
            src = snap["source_ts"] or snap["fetched_at"]
            t1, t2, t3, t4, t5, t6 = st.columns(6)
            t1.metric("Edad del feed", f"{int(now - src)} s")
            t2.metric("Latencia Renfe", f"{snap['latency_ms']} ms" if snap["latency_ms"] is not None else "—")
            t3.metric("Trenes con posición", len(df))
            t4.metric("Sin posición", snap["no_position"])
            t5.metric("GPS > 3 min", int((gps_num > 180).sum()) if len(gps_num) else 0)
            t6.metric("Lecturas / duplicadas", f"{snap['fetch_count']} / {snap['duplicate_polls']}")
            nh = pd.DataFrame(snap["net_hist"])
            if len(nh) >= 2:
                nh["hora"] = pd.to_datetime(nh["ts"], unit="s")
                nh = nh.set_index("hora")
                g1, g2 = st.columns(2)
                with g1:
                    st.caption("Flota: trenes, retrasados y a baja velocidad")
                    st.line_chart(nh[["trenes", "retrasados", "lentos"]])
                with g2:
                    st.caption("Riesgo máximo de la red y trenes detenidos")
                    st.line_chart(nh[["riesgo", "detenidos"]])
            else:
                st.caption("Las series se dibujan a partir de la segunda lectura válida.")
            if not df.empty:
                sp = df.loc[df["speed_kmh"] > 0, "speed_kmh"]
                if len(sp):
                    h, edges = np.histogram(sp, bins=[0, 5, 30, 60, 90, 120, 160, 200, 250, 350])
                    st.caption("Distribución de velocidades (km/h)")
                    st.bar_chart(pd.DataFrame({"trenes": h}, index=[f"{int(a)}-{int(b)}" for a, b in zip(edges[:-1], edges[1:])]))
                if len(gps_num) and gps_num.notna().any():
                    old = df.assign(gps=gps_num).nlargest(8, "gps")[["cod_comercial", "tipo", "gps", "speed_kmh"]]
                    st.caption("Trenes con la señal GPS más antigua")
                    st.dataframe(old.rename(columns={"cod_comercial": "Tren", "tipo": "Tipo", "gps": "Edad GPS (s)",
                                                     "speed_kmh": "km/h"}), hide_index=True)

        with t_inc:
            if not snap["inc_cfg"]:
                st.info("Sin fuente de incidencias configurada. Adif no ofrece un JSON público que yo conozca "
                        "(su web es adif.es/estado-de-la-red). Si dispones de una URL JSON, indícala en ADIF_INCIDENTS_URL o en "
                        "CANALES: lista o dict con 'incidencias'/'avisos', campos titulo, texto, ambito y, opcionalmente, "
                        "'tramo': [[lat,lon],[lat,lon]] para dibujar el corte. Mientras tanto usa TRAMOS CORTADOS.")
            elif snap["inc_ok"] is False:
                st.warning("Adif no responde; se reintenta cada 3 minutos.")
            for i in snap["incidents"]:
                st.markdown(f'<div class="inc {i["nivel"]}"><b>{esc(i["titulo"])}</b>{esc(i["texto"])}'
                            f'<br><small style="color:#7d8da0">{esc(i["ambito"])}</small></div>', unsafe_allow_html=True)
            if snap["inc_cfg"] and snap["inc_ok"] and not snap["incidents"]:
                st.caption("Adif no publica ninguna incidencia en este momento.")

        with t_reg:
            hist = db_recent(200) if snap["db_ok"] else pd.DataFrame(mon.recent_events(200))
            if hist.empty:
                st.caption("Aún no hay eventos registrados.")
            else:
                st.dataframe(hist, hide_index=True)
                st.download_button("⬇ Descargar CSV", hist.to_csv(index=False).encode("utf-8"),
                                   file_name="ebm_eventos.csv", mime="text/csv", key="dl_ev")
            if not snap["db_ok"]:
                st.caption("⚠ No se pudo abrir SQLite; se muestra solo el historial en memoria y no hay memoria de 30 días.")

        with t_sis:
            st.caption(
                f"Sondeos duplicados ignorados: {snap['duplicate_polls']} · Lecturas válidas: {snap['fetch_count']} · "
                f"Sondeo cada {snap['poll_s']} s · Recibidos del feed: {snap['raw_count']} · Sin posición: {snap['no_position']} · "
                f"Estaciones cargadas: {len(mon.stations)} · SQLite: {'ok' if snap['db_ok'] else 'no disponible'}"
                + (f" · Último error: {snap['last_error']}" if snap["last_error"] else ""))
            dbg = snap["routes_dbg"]
            st.markdown(f"**Rutas y horarios:** {len(snap['routes'])} trenes con paradas"
                        + (f" · registros: {dbg['registros']} · campos del primer registro: {dbg['campos']}" if dbg else "")
                        + (f" · problema: {snap['routes_error']}" if snap["routes_error"] else ""))
            e1, e2 = st.columns([2, 1])
            with e1:
                st.markdown(f"**Estaciones:** {len(mon.stations)} cargadas"
                            + (f" · último problema: {snap['stations_error']}" if snap["stations_error"] else ""))
                up = st.file_uploader("Subir estaciones propias (GeoJSON, o CSV con lat, lon, codigo, nombre, provincia)",
                                      type=["geojson", "json", "csv"], key="up_est")
                if up is not None and ss.get("up_sig") != (up.name, up.size):
                    try:
                        text = up.getvalue().decode("utf-8", "ignore")
                        est = parse_stations_csv(text) if up.name.lower().endswith(".csv") else parse_stations(json.loads(text))
                        if est:
                            mon.set_stations(est)
                            save_stations_cache(est)
                            ss.up_sig = (up.name, up.size)
                            st.success(f"{len(est)} estaciones cargadas y guardadas.")
                        else:
                            st.error("No encontré estaciones con coordenadas en ese archivo.")
                    except ValueError:
                        st.error("Archivo no válido.")
            with e2:
                st.button("🔄 Reintentar descarga", key="btn_retry_est", on_click=cb_retry_stations, **stretch)
            st.caption("Emergency Brake Monitor es independiente: no está vinculado a Renfe ni a Adif y usa datos públicos. Las alertas detectan la situación, no sustituyen a los sistemas de seguridad ferroviaria. "
                       "Los datos de posición pueden tener retraso o errores. Los tramos automáticos son aproximados.")

    # ================= EVENTOS NUEVOS → pitidos / sirena en ESTA pestaña =================
    pending = []
    if "last_seq" not in ss:
        ss.last_seq = snap["seq"]
        worst = max(snap["active"], key=lambda e: LEVELS[e["kind"]]["rank"], default=None)
        if worst and LEVELS[worst["kind"]]["rank"] >= siren_rank:
            arm_siren(worst["kind"], worst["msg"])
    new_events, cur_seq = mon.events_since(ss.last_seq)
    ss.last_seq = cur_seq
    if new_events:
        pending = list(new_events)
        for e in new_events:
            lvl = LEVELS[e["kind"]]
            try:
                st.toast(f"{lvl['label']}: {e['msg']}", icon=lvl["icon"])
            except Exception:  # noqa: BLE001
                st.toast(f"{lvl['label']}: {e['msg']}")
            if e.get("phase") == "nuevo" and lvl["rank"] >= siren_rank and lvl["rank"] > 0:
                arm_siren(e["kind"], e["msg"])

    # ================= PARTE SUPERIOR =================
    n_stop = int((df["is_stopped"] == True).sum()) if not df.empty else 0  # noqa: E712
    n_early = int((df["is_suspect"] == True).sum()) if not df.empty else 0  # noqa: E712
    n_brake = int((df["braking"] == True).sum()) if not df.empty else 0  # noqa: E712
    canales = mon.channel_names()
    siren = ss.get("siren")
    top_score = max((v["score"] for v in scores.values()), default=0)
    lvl_txt, lvl_cls, lvl_col = risk_level(top_score)
    a24 = count_kind(hist_df, "accident", 86400)
    targets = [e for e in snap["active"] if e.get("lat") is not None]
    target = max(targets, key=lambda e: LEVELS[e["kind"]]["rank"], default=None)

    with top:
        st.markdown(
            f'<div class="cp-bar"><div><div class="cp-title">🚆 EMERGENCY BRAKE MONITOR'
            f'<small>ALERTA TEMPRANA DE TRENES DETENIDOS EN VÍA</small></div>'
            f'<div class="cp-sub">Datos públicos de posición ferroviaria · última lectura {fmt_clock(snap["fetched_at"])} · '
            f'{len(df)} trenes con posición</div></div>'
            f'<div class="cp-clock">{datetime.now(TZ).strftime("%H:%M:%S")} <span class="cp-sub">LOCAL</span></div></div>',
            unsafe_allow_html=True)

        feed_state, feed_txt = ("warn", "CONGELADO") if snap["frozen"] else \
            ("warn", "SIN RED") if snap["stale"] else ("ok", "EN VIVO")
        if siren:
            sir_state, sir_txt = "warn", "ACTIVA"
        elif not ss.audio_ready:
            sir_state, sir_txt = "caution", "SIN ACTIVAR"
        elif ss.get("mute", False):
            sir_state, sir_txt = "caution", "MUTE"
        else:
            sir_state, sir_txt = "ok", "ARMADA"
        n_risk = len(risk_alerts) + len(cut_alerts)
        st.markdown('<div class="ann-grid">' + "".join([
            ann("Accidente", len(acc), "warn" if acc else "ok"),
            ann("Riesgo", n_risk, "warn" if n_risk else "ok"),
            ann("Detenidos", n_stop, "warn" if n_stop else "ok"),
            ann("Avisos", n_early, "caution" if n_early else "ok"),
            ann("Frenadas", n_brake, "caution" if n_brake else "ok"),
            ann("Tramos cortados", len(snap["cuts"]), "warn" if snap["cuts"] else "ok"),
            ann("Accid. 24 h", a24, "caution" if a24 else "ok"),
            ann("Estaciones", len(mon.stations) if mon.stations else "SIN DATOS", "ok" if mon.stations else "warn"),
            ann("Feed de datos", feed_txt, feed_state),
            ann("Monitor", "ACTIVO" if snap["thread_alive"] else "CAÍDO", "ok" if snap["thread_alive"] else "warn"),
            ann("Canales", len(canales) if canales else "NINGUNO", "ok" if canales else "caution"),
            ann("Sirena", sir_txt, sir_state),
            ann("Memoria 30 d", "SQLITE" if snap["db_ok"] else "NO", "ok" if snap["db_ok"] else "caution"),
        ]) + "</div>", unsafe_allow_html=True)

        b1, b2, b3, b4, b5 = st.columns([1.1, 1, 1, 1, 2.4])
        with b1:
            if not ss.audio_ready:
                if st.button("🔊 ACTIVAR ALERTAS", key="btn_audio", **stretch):
                    ss.audio_ready = True
                    st.rerun()
            else:
                st.success("🔔 Alertas ON", icon="✅")
        with b2:
            st.button("🚨 Probar sirena", key="btn_test_siren", on_click=test_siren, **stretch)
        with b3:
            st.checkbox("🔇 Silenciar sonido", key="mute")
        with b4:
            st.checkbox("🔁 Sonido de respaldo", key="audio_backup",
                        help="Sirena con reproductor nativo en bucle. Actívalo si la prueba no suena.")
        with b5:
            render_html(STATUS_HTML, height=34)
        a1, a2, a3, a4, a5 = st.columns(5)
        with a1:
            st.button("🔄 Actualizar ahora", key="btn_refresh", on_click=cb_refresh, **stretch)
        with a2:
            st.button("🎯 Ir a la alerta", key="btn_goto", disabled=target is None, **stretch,
                      on_click=cb_focus, args=(target["lat"], target["lon"], 11) if target else (0, 0, 6),
                      help="Centra el mapa en la alerta más grave activa.")
        with a3:
            st.button("🇪🇸 Toda España", key="btn_spain", on_click=cb_reset_view, **stretch)
        with a4:
            if st.button("🔔 Probar pitidos", key="btn_beeps", **stretch):
                pending.append(make_event("stopped", "stopped|prueba", "Prueba de pitidos: si los oyes, el audio funciona."))
        with a5:
            st.checkbox("🧪 Modo demo", key="demo_mode", help="Trenes simulados para probar mapa, riesgo, tramos y sirena.")
            st.caption(f"Latencia: {snap['latency_ms'] if snap['latency_ms'] is not None else '—'} ms · "
                       f"refresco UI {int(ss.get('refresh_s', DEFAULT_REFRESH_S))} s")
        if ss.get("render_html_error"):
            st.error(f"⚠ El puente de audio no se pudo cargar ({ss.render_html_error}). "
                     "Se usará automáticamente el reproductor de respaldo.")
        if not ss.audio_ready:
            st.caption("🔕 Pulsa «Activar alertas» y luego «Probar sirena» para comprobar que suena.")
        if snap["stale"]:
            st.warning("⚠ Sin conexión con Renfe: se muestra la última lectura válida.")
        if snap["frozen"]:
            st.warning(f"🧊 El feed de Renfe no cambia desde hace {int(snap['frozen_for'])} s: "
                       "la detección está en pausa para evitar falsas alarmas.")
        if snap["fetch_count"] < 2:
            st.info("Primera lectura: velocidad, rumbo y detenciones se calculan desde la segunda actualización.")
        if not mon.stations:
            st.error(f"🏁 No hay estaciones cargadas ({snap['stations_error'] or 'descarga pendiente'}). Sin ellas NO se puede "
                     "detectar un tren detenido en vía. Sube un archivo en la pestaña SISTEMA o reintenta la descarga.")
        if demo:
            st.warning("🧪 MODO DEMO: trenes SIMULADOS (nada de esto es real, no se envía a Telegram/ntfy ni se guarda). "
                       "En ~2 minutos el tren DEMO-P queda parado y DEMO-A se le acerca: verás accidente, tramo cortado y sirena.")
        elif snap["newest_gps_age"] is not None and snap["newest_gps_age"] > full_cfg["gps_stale_s"]:
            st.warning(f"🕒 Datos antiguos: la posición más reciente del feed es de hace {mmss(snap['newest_gps_age'])} (min:s). "
                       "Los trenes sin señal se pintan en gris y no generan alarmas.")
        elif len(df) == 0:
            ult = snap["source_ts"]
            hace = f"último dato del feed hace {mmss(time.time() - ult)} (min:s)" if ult else "sin fecha en el feed"
            st.info(f"El feed no trae trenes con posición ahora mismo (recibidos: {snap['raw_count']}, sin posición: "
                    f"{snap['no_position']}, {hace}). De madrugada es normal: casi no circulan trenes de larga distancia. "
                    "Activa «🧪 Modo demo» para probar la herramienta.")

    # ================= MASTER WARNING + RECONOCER =================
    with alarm_zone:
        if siren or risk_alerts or cut_alerts or acc:
            lines = "".join(f"<div>💥 <b>Tren {esc(a['cod'])}</b> ({esc(a['tipo'])}) detenido en vía · {esc(', '.join(a['why']))}</div>"
                            for a in acc[:4])
            lines += "".join(
                f"<div><b>Tren {esc(a['moving'])}</b> ({a['speed_kmh']} km/h) se acerca al <b>tren {esc(a['stopped'])}</b> "
                f"detenido · {a['dist_m']} m · TTC <b>{a['ttc_s']} s</b></div>" for a in risk_alerts[:4])
            lines += "".join(
                f"<div>🚧 <b>Tren {esc(a['moving'])}</b> ({a['speed_kmh']} km/h) se dirige al tramo cortado "
                f"«{esc(a['cut_name'])}» · {a['dist_m']} m · TTC <b>{a['ttc_s']} s</b></div>" for a in cut_alerts[:4])
            if not lines and siren:
                lines = f"<div>{esc(siren['msg'])}</div>"
            head = siren["label"] if siren else ("POSIBLE ACCIDENTE" if acc else "RIESGO CRÍTICO")
            since = f" · lleva {mmss(time.time() - siren['since'])}" if siren else ""
            st.markdown(f'<div class="master"><h4>⚠ MASTER WARNING · {esc(head)}{since}</h4>{lines}</div>',
                        unsafe_allow_html=True)
        if siren:
            tag = "tono de dos notas" if siren["kind"] == "risk" else "barrido continuo"
            st.button(f"✔ RECONOCER Y SILENCIAR SIRENA  ({tag})", key="btn_ack", type="primary",
                      on_click=ack_siren, **stretch)
            if not sound_on:
                st.caption("🔕 La sirena está armada pero el sonido está desactivado o sin desbloquear en esta pestaña.")

    # ================= CUERPO: filtros, mapa y paneles =================
    with main_zone:
        f1, f2, f3, f4 = st.columns([3, 1.2, 1, 1])
        with f1:
            todos = list(GRUPOS.keys()) + ["Otros"]
            cuenta = df["grupo"].value_counts().to_dict() if not df.empty else {}
            fmt = lambda g: f"{g} · {cuenta.get(g, 0)}"  # noqa: E731
            if hasattr(st, "pills"):
                grupos_sel = st.pills("Tipos de tren", todos, selection_mode="multi", default=todos, key="grupos_pills",
                                      format_func=fmt, label_visibility="collapsed")
            else:
                grupos_sel = st.multiselect("Tipos de tren", todos, default=todos, key="grupos", format_func=fmt,
                                            label_visibility="collapsed")
            grupos_sel = list(grupos_sel or [])
        with f2:
            filtro_parados = st.checkbox("🚨 Solo detenidos / avisos")
        with f3:
            usar_cluster = st.checkbox("🗂 Agrupar trenes")
        with f4:
            ver_estaciones = st.checkbox("🏁 Estaciones", value=True, key="ver_est")
        m1, m2, m3, m4, m5 = st.columns([1.3, 1.1, 1.2, 1.2, 1.4])
        with m1:
            map_engine = st.radio("Motor de mapa", ["Interactivo", "Estático (seguro)"], horizontal=True,
                                  key="map_engine", label_visibility="collapsed",
                                  help="Si el interactivo no se ve, usa el estático: siempre se dibuja, sin clic.")
        with m2:
            theme = st.radio("Mapa", ["Claro", "Oscuro", "OSM"], index=0, horizontal=True, key="map_theme",
                             label_visibility="collapsed", help="El fondo elegido se mantiene en cada actualización.")
        with m3:
            ver_tramos = st.checkbox("🚧 Tramos cortados", value=True, key="ver_tramos")
        with m4:
            ver_hist = st.checkbox("🕘 Historial 30 d", key="ver_hist", help="Puntos de incidentes de los últimos 30 días.")
        with m5:
            remember_view = st.checkbox("🧭 Recordar zoom", key="remember_view",
                                        help="Desactivado por defecto: en algunas versiones provoca re-renders en bucle.")

        df_f = df[df["grupo"].isin(grupos_sel)] if not df.empty else df
        if filtro_parados and not df_f.empty:
            df_f = df_f[(df_f["is_stopped"] == True) | (df_f["is_suspect"] == True)]  # noqa: E712

        total = len(df_f)
        ret_clip = df_f["retraso_min"].clip(lower=0) if total else pd.Series(dtype=float)
        retrasados = int((df_f["retraso_min"] >= 5).sum()) if total else 0
        mediana = float(ret_clip.median()) if total else 0.0
        maximo = int(df_f["retraso_min"].max()) if total else 0
        vmed = float(df_f.loc[df_f["speed_kmh"] > SLOW_KMH, "speed_kmh"].mean()) if total and \
            (df_f["speed_kmh"] > SLOW_KMH).any() else 0.0
        st.markdown(
            '<div class="gauges">'
            f'<div class="gauge"><b style="color:{lvl_col}">{top_score}</b><span>Riesgo red · {lvl_txt}</span></div>'
            f'<div class="gauge"><b>{total}</b><span>En mapa</span></div>'
            f'<div class="gauge"><b style="color:#f1c40f">{retrasados}</b><span>Con retraso ≥5 min</span></div>'
            f'<div class="gauge"><b style="color:#39ff88">{mediana:.0f} min</b><span>Retraso mediano</span></div>'
            f'<div class="gauge"><b style="color:#ff9f1a">{maximo} min</b><span>Retraso máximo</span></div>'
            f'<div class="gauge"><b>{vmed:.0f}</b><span>km/h medios en marcha</span></div>'
            '</div>', unsafe_allow_html=True)

        col_map, col_panel = st.columns([3, 1.25])

        with col_map:
            z1, z2, z3, z4, z5 = st.columns(5)
            z1.button("➕ Acercar", key="z_in", on_click=cb_zoom, args=(1,), **stretch)
            z2.button("➖ Alejar", key="z_out", on_click=cb_zoom, args=(-1,), **stretch)
            z3.button("🇪🇸 Toda España", key="z_all", on_click=cb_reset_view, **stretch)
            z4.button("🎯 A la alerta", key="z_alert", disabled=target is None, **stretch, on_click=cb_focus,
                      args=(target["lat"], target["lon"], 11) if target else (0, 0, 6))
            z5.button("🔄 Actualizar", key="z_ref", on_click=cb_refresh, **stretch)
            st.markdown('<div class="leg"><span style="--c:#2ecc71">≤5 min</span><span style="--c:#f1c40f">6-15</span>'
                        '<span style="--c:#e67e22">16-30</span><span style="--c:#e74c3c">&gt;30</span>'
                        '<span style="--c:#ff9f1a">aviso temprano</span><span style="--c:#ff3232">detenido</span>'
                        '<span style="--c:#ff0000">posible accidente</span><span style="--c:#bd5fff">frenada brusca</span>'
                        '<span style="--c:#ff2d2d">tramo cortado ▬ ▬</span></div>', unsafe_allow_html=True)
            focus = ss.get("focus")
            if focus:
                center, zoom = [focus[0], focus[1]], focus[2]
            elif remember_view:
                center, zoom = ss.get("map_center", [40.0, -3.5]), ss.get("map_zoom", 6)
            else:
                center, zoom = [40.0, -3.5], 6
            m = make_base_map(theme, center, zoom)

            if ver_estaciones and mon.has_stations():
                fg_est = folium.FeatureGroup(name="Estaciones", show=True)
                for s in mon.stations:
                    folium.CircleMarker([s["lat"], s["lon"]], radius=4, color="#1f5fa8", fill=True, fill_color="#3b8eea",
                                        fill_opacity=0.85, weight=1,
                                        tooltip=(s["n"] or s["code"] or "estación")).add_to(fg_est)
                fg_est.add_to(m)
            for fn, args in ((add_history, (m, hist_df)), (add_cuts, (m, snap["cuts"]))):
                if (fn is add_history and not (ver_hist and not hist_df.empty)) or (fn is add_cuts and not ver_tramos):
                    continue
                try:
                    fn(*args)
                except Exception as e:  # noqa: BLE001 - las capas extra nunca bloquean los trenes
                    st.caption(f"⚠ Capa omitida ({type(e).__name__}).")
            add_trains(m, df_f, info, ss.get("sel_train"), acc_cods, scores, usar_cluster, full_cfg["gps_stale_s"])
            st.caption(f"🚆 {len(df_f)} trenes dibujados de {len(df)} con posición · 🏁 {len(mon.stations)} estaciones cargadas"
                       f"{'' if ver_estaciones else ' (ocultas)'} · tema de mapa: {theme}")

            map_data = None
            use_static = not map_engine.startswith("Interactivo")
            if not use_static:
                returned = ["last_object_clicked", "last_object_clicked_tooltip"]
                if remember_view:
                    returned += ["center", "zoom"]
                try:
                    map_data = st_folium(m, key=f"mapa_{theme}_{ss.view_nonce}", use_container_width=True, height=620,
                                         returned_objects=returned)
                except Exception as e:  # noqa: BLE001 - el mapa nunca debe tumbar la herramienta
                    st.error(f"El mapa interactivo falló ({type(e).__name__}); se muestra el mapa estático.")
                    use_static = True
            if use_static:
                st.caption("🗺 Mapa estático: se dibuja siempre, pero sin clic en trenes (usa el popup de cada punto).")
                render_html(m.get_root().render(), height=640)
            if map_data and remember_view:
                c, z = map_data.get("center"), map_data.get("zoom")
                if c and z:
                    ss.map_center = [c["lat"], c["lng"]]
                    ss.map_zoom = z
            clicked = find_clicked_train(df_f, map_data)
            if clicked is not None:
                sig = (clicked["cod_comercial"], str((map_data or {}).get("last_object_clicked")))
                if ss.get("last_click_sig") != sig:
                    ss.last_click_sig = sig
                    ss.sel_train = clicked["cod_comercial"]

        with col_panel:
            tab_arr, tab_al, tab_rk, tab_tren, tab_list = st.tabs(["⏱ RETRASOS", "🚨 ALERTAS", "🎚 RIESGO", "🚆 TREN", "📋 TRENES"])

            with tab_al:
                active = sorted(snap["active"], key=lambda e: -LEVELS[e["kind"]]["rank"])
                if not active:
                    st.markdown('<div class="eicas"><div class="nominal">● SISTEMA NOMINAL — sin trenes detenidos '
                                'lejos de estaciones.</div></div>', unsafe_allow_html=True)
                else:
                    body = "".join(
                        f'<div class="msg {"risk" if e["kind"] == "accident" else e["kind"]}"><b>{LEVELS[e["kind"]]["icon"]} '
                        f'{LEVELS[e["kind"]]["label"]} · {mmss(time.time() - e.get("first", time.time()))}</b>{esc(e["msg"])}</div>'
                        for e in active[:25])
                    st.markdown(f'<div class="eicas">{body}</div>', unsafe_allow_html=True)

            with tab_rk:
                st.markdown(f'<div class="riskbox {lvl_cls}"><b>{top_score}</b><div><span>ÍNDICE DE RIESGO DE LA RED</span><br>'
                            f'<span style="color:{lvl_col};font-weight:700">{lvl_txt}</span></div></div>', unsafe_allow_html=True)
                ranking = sorted(((c, v) for c, v in scores.items() if v["score"] > 0), key=lambda x: -x[1]["score"])[:10]
                if not ranking:
                    st.caption("Ningún tren con riesgo apreciable.")
                for c, v in ranking:
                    nm, _, col = risk_level(v["score"])
                    st.markdown(
                        f'<div class="rrow"><div><b>{esc(c)}</b><small>{esc(" · ".join(v["why"]))}</small></div>'
                        f'<div class="bar"><i style="width:{v["score"]}%;background:{col}"></i></div><em>{v["score"]}</em></div>',
                        unsafe_allow_html=True)
                st.caption("0-29 bajo · 30-54 medio · 55-79 alto · 80+ crítico. Suma detención, frenada, alcance, "
                           "tramo cortado, accidente y pérdida de GPS.")

            with tab_arr:
                min_ret = st.slider("Mostrar retrasos desde (min)", 1, 60, 5, key="min_ret")
                if total:
                    rc = df_f["retraso_min"]
                    st.markdown(
                        '<div class="leg">'
                        f'<span style="--c:#f1c40f">≥5 min · {int((rc >= 5).sum())}</span>'
                        f'<span style="--c:#e67e22">≥15 · {int((rc >= 15).sum())}</span>'
                        f'<span style="--c:#e74c3c">≥30 · {int((rc >= 30).sum())}</span>'
                        f'<span style="--c:#8e0000">≥60 · {int((rc >= 60).sum())}</span></div>', unsafe_allow_html=True)
                zonas = [z[0] for z in ZONAS]
                if hasattr(st, "pills"):
                    zona = st.pills("Zona de llegada", zonas, selection_mode="single", default=zonas[0], key="zona_pills",
                                    label_visibility="collapsed") or zonas[0]
                else:
                    zona = st.radio("Zona de llegada", zonas, horizontal=True, key="zona", label_visibility="collapsed")
                ret = df_f[df_f["retraso_min"] >= min_ret] if total else df_f
                n_zona_antes = len(ret)
                if not ret.empty:
                    ret = ret[ret["destino"].map(lambda c: in_zone(zona, c, info))].sort_values("retraso_min", ascending=False)
                if len(ret):
                    st.caption(f"{len(ret)} tren(es) con {min_ret} min de retraso o más · derecha: llegada al destino "
                           "(tachada = prevista, debajo = estimada)" if snap["routes"] else
                           f"{len(ret)} tren(es) con {min_ret} min de retraso o más · sin horarios de destino: "
                           "se muestra la próxima parada")
                elif n_zona_antes:
                    st.caption("Ninguno en esta zona (si falta la provincia de las estaciones, usa «Toda España»).")
                else:
                    st.caption(f"Ningún tren de los elegidos tiene {min_ret} min de retraso o más.")
                ver_todos = st.checkbox("Ver todos", key="arr_all") if len(ret) > 12 else False
                rows_html = ""
                for _, t in (ret if ver_todos else ret.head(12)).iterrows():
                    nv = "grave" if t["retraso_min"] >= 15 else "leve"
                    where = (f"En {esc(label_est(t['est_ant'], info))}" if t["est_ant"] == t["est_sig"]
                             else f"Entre {esc(label_est(t['est_ant'], info))} y {esc(label_est(t['est_sig'], info))}")
                    plan = planned_arrival(snap["routes"], t["cod_comercial"], t["destino"])
                    hs = (f"<del>{plan}</del>{add_minutes_hhmm(plan, max(0, int(t['retraso_min'])))}" if plan else
                          (f"{esc(label_est(t['est_sig'], info))}<br>{esc(t['hora_sig'])}" if t["hora_sig"] else ""))
                    rows_html += (
                        f'<div class="arr {nv}"><div class="min">+{int(t["retraso_min"])}</div>'
                        f'<div><div class="t">{esc(t["tipo"])} {esc(label_est(t["origen"], info))} → '
                        f'{esc(label_est(t["destino"], info))}<small>{esc(t["cod_comercial"])}</small></div>'
                        f'<div class="d">{where}</div></div><div class="h">{hs}</div></div>')
                if rows_html:
                    st.markdown(rows_html, unsafe_allow_html=True)

            with tab_tren:
                opciones = ["—"] + sorted(df["cod_comercial"].tolist()) if not df.empty else ["—"]
                if ss.get("sel_train") not in opciones:
                    ss.sel_train = "—"
                st.selectbox("Buscar / seleccionar tren", opciones, key="sel_train")
                t = None
                if ss.sel_train != "—":
                    cur = df[df["cod_comercial"] == ss.sel_train]
                    t = cur.iloc[0] if not cur.empty else None
                if t is None:
                    st.caption("Pulsa un tren en el mapa o elígelo en la lista.")
                else:
                    cod = t["cod_comercial"]
                    sc = scores.get(cod, {"score": 0, "why": []})
                    rn, _, rcol = risk_level(sc["score"])
                    est = "💥 Posible accidente" if cod in acc_cods else "🔴 Detenido en vía" if t["is_stopped"] else \
                        ("🟠 Aviso temprano" if t["is_suspect"] else "🟢 En marcha")
                    where = (f"En {esc(label_est(t['est_ant'], info))}" if t["est_ant"] == t["est_sig"]
                             else f"Entre {esc(label_est(t['est_ant'], info))} y {esc(label_est(t['est_sig'], info))}")
                    vel_txt = "Parado" if t["speed_kmh"] < 4 else "≈ %d km/h" % round(t["speed_kmh"])
                    gps_txt = f"hace {int(t['gps_age_s'])} s" if pd.notna(t["gps_age_s"]) else "—"
                    spark = sparkline(snap["hist"].get(cod, []))
                    st.markdown(
                        f'<div class="ficha"><h3>{esc(t["tipo"])} {esc(cod)}</h3>'
                        f'<div class="r">{esc(label_est(t["origen"], info))} → {esc(label_est(t["destino"], info))}</div><dl>'
                        f'<dt>Estado</dt><dd>{est}</dd>'
                        f'<dt>Riesgo</dt><dd style="color:{rcol}">{sc["score"]} · {rn}</dd>'
                        f'<dt>Retraso</dt><dd>{fmt_delay(t["retraso_min"])}</dd>'
                        f'<dt>Velocidad</dt><dd>{vel_txt}</dd>'
                        f'<dt>Instantánea</dt><dd>{t["inst_kmh"]:.0f} km/h</dd>'
                        + (f'<dt>Deceleración</dt><dd>{t["decel_ms2"]:.2f} m/s²</dd>' if t["decel_ms2"] > 0.1 else "")
                        + (f'<dt>Rumbo</dt><dd>{round(t["heading"])}°</dd>' if t["has_heading"] else "")
                        + f'<dt>Dónde</dt><dd>{where}</dd>'
                        + (f'<dt>Próx. parada</dt><dd>{esc(t["hora_sig"])}</dd>' if t["hora_sig"] else "")
                        + (lambda p: (f'<dt>Llegada prevista</dt><dd>{p}</dd><dt>Llegada estimada</dt>'
                                      f'<dd>{add_minutes_hhmm(p, max(0, int(t["retraso_min"])))}</dd>') if p else "")(
                            planned_arrival(snap["routes"], cod, t["destino"]))
                        + (f'<dt>A estación</dt><dd>{fmt_m(t["dist_to_station"])} m</dd>' if t["dist_to_station"] is not None else "")
                        + (f'<dt>Baja velocidad</dt><dd>{mmss(t["stopped_for_s"])}</dd>' if t["stopped_for_s"] > 0 else "")
                        + f'<dt>Señal GPS</dt><dd>{gps_txt}</dd><dt>Material</dt><dd>{esc(t["mat"])}</dd>'
                        f'<dt>PMR</dt><dd>{"Sí" if t["accesible"] else "No"}</dd></dl>'
                        + (f'<div style="margin-top:8px">{spark}<div class="r" style="margin:2px 0 0">velocidad, últimas lecturas</div></div>' if spark else "")
                        + '</div>', unsafe_allow_html=True)
                    r1, r2 = st.columns(2)
                    r1.button("🎯 Centrar mapa", key="t_center", on_click=cb_focus, args=(t["lat"], t["lon"], 12), **stretch)
                    r2.button("🚧 Cortar su tramo", key="t_cut", on_click=cb_cut_train, args=(cod,), **stretch)
                    r3, r4 = st.columns(2)
                    r3.button("💥 Confirmar accidente", key="t_conf", on_click=cb_confirm, args=(cod,), **stretch)
                    r4.button("✖ Falsa alarma", key="t_dis", on_click=cb_dismiss, args=(cod,),
                              disabled=cod not in acc_cods, **stretch)
                    gm = f"https://www.google.com/maps?q={t['lat']:.5f},{t['lon']:.5f}"  # noqa: E501
                    if hasattr(st, "link_button"):
                        st.link_button("📍 Abrir en Google Maps", gm, **stretch)
                    else:
                        st.markdown(f"[📍 Abrir en Google Maps]({gm})")

    # (la pestaña TRENES se rellena aquí para no alterar el orden de los paneles)
    with col_panel:
        with tab_list:
            if df_f.empty:
                st.caption("No hay trenes con los filtros actuales.")
            else:
                vista = df_f.assign(riesgo=df_f["cod_comercial"].map(lambda c: scores.get(c, {}).get("score", 0)))[
                    ["cod_comercial", "tipo", "retraso_min", "speed_kmh", "riesgo", "stopped_for_s", "lat", "lon"]]
                st.dataframe(vista.rename(columns={"cod_comercial": "Tren", "tipo": "Tipo", "retraso_min": "Retraso",
                                                   "speed_kmh": "km/h", "riesgo": "Riesgo", "stopped_for_s": "Baja vel. (s)"}),
                             hide_index=True)

    # ================= SINCRONIZACIÓN CON EL NAVEGADOR (una vez por ejecución) =================
    siren = ss.get("siren")
    siren_kind = siren["kind"] if (siren and sound_on) else None
    siren_title = f"🚨 {siren['label']}" if siren_kind else ""
    token = f"{ss.siren_ver}-{time.time() if pending else 0}"
    bridge_ok = browser_sync(pending, sound_on, siren_kind, siren_title, token)
    if siren_kind and (ss.get("audio_backup") or not bridge_ok):
        play_backup_siren(siren_kind)
    elif pending and sound_on and (ss.get("audio_backup") or not bridge_ok):
        top_ev = max(pending, key=lambda e: LEVELS[e["kind"]]["rank"])
        if LEVELS[top_ev["kind"]]["beeps"]:
            wav = make_siren_wav("stopped")
            try:
                st.audio(wav, format="audio/wav", autoplay=True)
            except TypeError:
                st.audio(wav, format="audio/wav")


def _running_in_streamlit():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    if _running_in_streamlit() or os.environ.get("EBM_LAUNCHED"):
        main()
    else:
        # `python emergency_brake_monitor.py`: se relanza con Streamlit y sin vigilancia de archivos
        # (evita el aviso «inotify watch limit reached» en Linux con carpetas grandes).
        env = dict(os.environ, EBM_LAUNCHED="1", STREAMLIT_SERVER_FILE_WATCHER_TYPE="none")
        sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", os.path.abspath(__file__),
                                  "--server.fileWatcherType", "none"], env=env))
