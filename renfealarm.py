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
import atexit
import hmac
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import wave
import zipfile
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
.msg.close { border-color:#ff1fa3; } .msg.close b { color:#ff5cc0; }
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
# Red completa: Cercanías / Rodalies / Tram en GTFS-RT (posiciones verificadas; retrasos y avisos: URLs habituales de Renfe)
URL_CERC_POS = "https://gtfsrt.renfe.com/vehicle_positions.json"
URL_CERC_TRIPS = "https://gtfsrt.renfe.com/trip_updates.json"
URL_CERC_ALERTS = "https://gtfsrt.renfe.com/alerts.json"
# GTFS estático de Renfe (stops.txt = estaciones con el MISMO código que usan los feeds)
# Listado oficial de estaciones de Renfe (código, nombre, coordenadas, provincia) — datos abiertos CC BY 4.0
RENFE_STATIONS_CSV_URLS = [
    "https://data.renfe.com/dataset/ed3d44e5-1d04-41d6-9aa5-396442bf3e07/resource/783e0626-6fa8-4ac7-a880-fa53144654ff/download/listado-estaciones-completo-act.csv",
    "https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv"]
EXTRA_POS_URLS = [u.strip() for u in os.getenv("EBM_EXTRA_GTFSRT", "").split(",") if u.strip().startswith(("http://", "https://"))]
GTFS_URLS = ["https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip",
             "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip"]

# Código de producto de Renfe (tabla contrastada con el visor público)
NOM_PROD = {99: "Simulacro", 200: "Cercanías", 201: "Rodalies", 2: "AVE", 25: "AVE", 28: "Avlo", 3: "Avant", 11: "Alvia", 10: "Euromed", 13: "Intercity",
            4: "Talgo", 5: "Altaria", 7: "Diurno", 8: "Estrella", 9: "Tren Hotel", 24: "AV City",
            14: "Andalucía Exprés", 15: "Catalunya Exprés", 16: "Media Distancia", 18: "Regional",
            19: "Regional Exprés", 20: "TRD"}
GRUPOS = {"AVE": [2, 25], "Avlo": [28], "Avant": [3], "Alvia": [11],
          "Euromed e Intercity": [10, 13, 4, 5, 7, 8, 9, 24],
          "Media distancia y regionales": [14, 15, 16, 18, 19, 20],
          "Cercanías y Rodalies": [200, 201]}

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
    "early_stop_s": 45, "min_stop_s": 120, "station_radius_m": 1200,
    "risk_dist_m": 5000, "risk_ttc_s": 120, "risk_heading_deg": 60, "risk_min_kmh": 30,
    "risk_include_suspect": True,
    "brake_min_kmh": 100, "brake_ms2": 1.0, "brake_station_m": 3000, "brake_hold_s": 120,
    "push_min_rank": 3,
    "accident_s": 600,          # detenido tanto tiempo lejos de estación => posible accidente
    "accident_max": 2,          # más candidatos simultáneos que esto = fallo de datos/calibración, no accidentes
    "cerc_stop_mult": 3,        # Cercanías: posiciones menos fiables => los tiempos se multiplican por esto
    "cut_half_km": 5,           # semilongitud (km) del tramo cortado automático alrededor del tren
    "close_on": True,           # detección de aproximación entre trenes por velocidades
    "close_gap_m": 8000,        # hueco máximo entre seguidor y tren de delante
    "close_closing_kmh": 30,    # el seguidor debe ir al menos así de más rápido
    "close_ttc_s": 120,         # aviso si alcanzaría al de delante en menos de esto
    "close_decel": 0.6,         # frenado de servicio supuesto (m/s²)
    "close_lateral_m": 250,     # desvío lateral máximo para considerar "misma vía"
    "close_heading_deg": 35,    # tolerancia de rumbo entre ambos trenes
    "gps_stale_s": 600,         # señal GPS más antigua que esto => tren "sin señal": no genera alarmas
    "cut_warn_m": 10000,        # distancia a la que un tren que se acerca a un tramo cortado genera aviso
}

LEVELS = {
    "early":    {"label": "AVISO TEMPRANO",    "icon": "🟡", "color": "#f1c40f", "rank": 1, "beeps": 2, "repeat_s": 180},
    "brake":    {"label": "FRENADA BRUSCA",    "icon": "🟠", "color": "#e67e22", "rank": 2, "beeps": 3, "repeat_s": 300},
    "stopped":  {"label": "DETENIDO EN VÍA",   "icon": "🔴", "color": "#ff3232", "rank": 3, "beeps": 4, "repeat_s": 120},
    "accident": {"label": "POSIBLE ACCIDENTE",  "icon": "💥", "color": "#ff0000", "rank": 5, "beeps": 10, "repeat_s": 60},
    "close":    {"label": "APROXIMACIÓN PELIGROSA", "icon": "⚡", "color": "#ff1fa3", "rank": 3, "beeps": 5, "repeat_s": 60},
    "risk":     {"label": "RIESGO CRÍTICO",    "icon": "🚨", "color": "#ff0000", "rank": 4, "beeps": 8, "repeat_s": 30},
    "system":   {"label": "AVISO DEL SISTEMA", "icon": "⚠", "color": "#8b949e", "rank": 0, "beeps": 1, "repeat_s": 900},
    "resolved": {"label": "RESUELTO",          "icon": "✅", "color": "#2ecc71", "rank": 0, "beeps": 0, "repeat_s": 10 ** 9},
}

BASE_COLUMNS = [
    "cod_comercial", "tipo", "grupo", "src", "status", "delay_known", "cod_prod", "lat", "lon", "retraso_min", "speed_kmh", "inst_kmh",
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
    if code == 99:
        return "Simulacro"
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
    for chunk in str(text or "").replace("\n", ";").split(";")[:500]:
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


def where_text(ant, sig, info):
    ant, sig = norm_code(ant), norm_code(sig)
    if ant and ant == sig:
        return f"En {label_est(ant, info)}"
    if ant and sig:
        return f"Entre {label_est(ant, info)} y {label_est(sig, info)}"
    if sig:
        return f"Hacia {label_est(sig, info)}"
    if ant:
        return f"Tras {label_est(ant, info)}"
    return ""


def train_in_zone(zone, row, info):
    """
    ¿Va el tren a esa zona? Orden de intentos: provincia de la estación destino -> nombre de la estación (o de CORTOS)
    -> coordenadas de la estación -> posición actual del tren dentro de la zona (si no se conoce el destino).
    """
    z = next((x for x in ZONAS if x[0] == zone), None)
    if z is None or z[1] is None:
        return True
    provs, box = z[1], z[2]
    code = norm_code(row["destino"])
    e = info.get(code)
    if e:
        p = norm_text(e.get("prov"))
        if p and any(p == x or p.endswith(" " + x) or p.startswith(x + " ") for x in provs):
            return True
        nm = norm_text(e.get("n"))
        if nm and any(x in nm for x in provs):
            return True
        if box and box[0] <= e["lat"] <= box[1] and box[2] <= e["lon"] <= box[3]:
            return True
        if p or nm:      # la estación se conoce y no está en esta zona
            return False
    nm = norm_text(CORTOS.get(code, ""))
    if nm and any(x in nm for x in provs):
        return True
    return bool(box) and box[0] <= row["lat"] <= box[1] and box[2] <= row["lon"] <= box[3]


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
        code = pick(props, ["codigo", "cod_estacion", "codEstacion", "codigoEstacion", "cdgoUIC", "codEst", "uic", "id"]) \
            or f.get("id")
        if not code:  # último recurso: cualquier propiedad que parezca un código numérico de estación
            code = next((v for v in props.values() if isinstance(v, (str, int)) and str(v).strip().isdigit()
                         and 4 <= len(str(v).strip()) <= 6), None)
        name = pick(props, ["nombre", "name", "nombreEstacion", "nombre_estacion", "descripcion", "desc", "estacion",
                            "nom", "label", "title", "station_name"])
        prov = pick(props, ["provincia", "province", "prov"])
        out.append({"code": norm_code(code), "n": str(name or ""), "prov": str(prov or ""), "lat": lat, "lon": lon})
    return out


OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
OVERPASS_QUERY = ('[out:json][timeout:90];area["ISO3166-1"="ES"][admin_level=2]->.es;'
                  '(node["railway"="station"]["station"!~"subway|light_rail|tram|monorail|funicular"](area.es);'
                  'node["railway"="halt"](area.es););out body;')


def parse_overpass(data):
    """Estaciones de OpenStreetMap (Overpass JSON) -> mismo formato que parse_stations."""
    out = []
    for el in (data or {}).get("elements", []):
        lat, lon = to_float(el.get("lat")), to_float(el.get("lon"))
        if lat is None or lon is None:
            continue
        tags = el.get("tags") or {}
        uic = str(tags.get("uic_ref") or "").strip()
        out.append({"code": norm_code(uic[-5:]) if uic.isdigit() else "", "n": str(tags.get("name") or ""),
                    "prov": str(tags.get("addr:province") or tags.get("is_in:province") or ""), "lat": lat, "lon": lon})
    return out


def parse_gtfs_stops_zip(content):
    """stops.txt de un GTFS (zip) -> estaciones con el código de Renfe (stop_id)."""
    import csv
    out = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("stops.txt")), None)
        if not name or z.getinfo(name).file_size > 150 * 1024 * 1024:   # tope contra "zip bombs"
            return out
        with z.open(name) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                lat, lon = to_float(r.get("stop_lat")), to_float(r.get("stop_lon"))
                if lat is None or lon is None:
                    continue
                out.append({"code": norm_code(r.get("stop_id")), "n": (r.get("stop_name") or "").strip(), "prov": "",
                            "lat": lat, "lon": lon})
    return out


def _d(x):
    return x if isinstance(x, dict) else {}


def parse_gtfsrt_vehicles(data):
    """Cercanías/Rodalies (GTFS-RT vehicle_positions.json) -> trenes con el mismo formato que flotaLD."""
    out = []
    for ent in _d(data).get("entity", []) or []:
        try:
            v = _d(_d(ent).get("vehicle"))
            pos = _d(v.get("position"))
            lat, lon = to_float(pos.get("latitude")), to_float(pos.get("longitude"))
            if lat is None or lon is None:
                continue
            veh = _d(v.get("vehicle"))
            label = str(veh.get("label") or veh.get("id") or _d(ent).get("id") or "")
            parts = label.split("-")
            line = parts[0] if parts else ""
            num = str(veh.get("id") or (parts[1] if len(parts) > 1 else ""))
            cod = f"{line}-{num}" if line and num else (label or str(_d(ent).get("id") or ""))
            status = str(v.get("currentStatus") or "")
            stop = norm_code(v.get("stopId"))
            out.append({"codComercial": cod, "codProduct": 201 if line.upper().startswith("R") else 200,
                        "latitud": lat, "longitud": lon, "ultRetraso": None, "time": to_float(v.get("timestamp")),
                        "codEstAnt": stop if status == "STOPPED_AT" else "", "codEstSig": stop, "codOrigen": "",
                        "codDestino": "", "mat": label, "accesible": False, "_src": "CERC", "_status": status,
                        "_trip": str(_d(v.get("trip")).get("tripId") or ""), "_delay_known": False})
        except (AttributeError, TypeError, ValueError):
            continue    # una entidad malformada no descarta al resto
    return out


def parse_gtfsrt_delays(data):
    """tripId -> retraso en minutos (GTFS-RT trip_updates)."""
    out = {}
    for ent in (data or {}).get("entity", []) or []:
        tu = ent.get("tripUpdate") if isinstance(ent, dict) else None
        if not isinstance(tu, dict):
            continue
        trip = (tu.get("trip") or {}).get("tripId")
        if not trip:
            continue
        d = to_float(tu.get("delay"))
        if d is None:
            for stu in tu.get("stopTimeUpdate") or []:
                for k in ("arrival", "departure"):
                    d = to_float((stu.get(k) or {}).get("delay"))
                    if d is not None:
                        break
                if d is not None:
                    break
        if d is not None:
            out[str(trip)] = int(round(d / 60.0))
    return out


def parse_gtfsrt_alerts(data, now=None):
    """Avisos oficiales (GTFS-RT alerts) -> mismo formato que las incidencias."""
    now = now or time.time()
    out = []

    def text(x):
        tr = (x or {}).get("translation") or []
        if not tr:
            return ""
        best = next((t for t in tr if str(t.get("language", "")).lower().startswith("es")), tr[0])
        return str(best.get("text", ""))

    for ent in (data or {}).get("entity", []) or []:
        a = ent.get("alert") if isinstance(ent, dict) else None
        if not isinstance(a, dict):
            continue
        periods = a.get("activePeriod") or []
        if periods and not any((to_float(p.get("start")) or 0) <= now <= (to_float(p.get("end")) or 1e18) for p in periods):
            continue
        effect = str(a.get("effect") or "")
        nivel = "grave" if effect in ("NO_SERVICE", "SIGNIFICANT_DELAYS", "DETOUR", "STOP_MOVED") else \
            "leve" if effect in ("REDUCED_SERVICE", "MODIFIED_SERVICE", "ADDITIONAL_SERVICE") else "info"
        ents = sorted({str(ie.get("routeId") or ie.get("stopId") or "") for ie in (a.get("informedEntity") or [])} - {""})
        out.append({"titulo": text(a.get("headerText")) or "Aviso", "texto": text(a.get("descriptionText")),
                    "ambito": ", ".join(ents)[:140], "nivel": nivel, "pts": [], "fuente": "Renfe (GTFS-RT)",
                    "causa": classify_cause(text(a.get("headerText")) + " " + text(a.get("descriptionText")))})
    return out


# Último recurso si NO hay descarga ni copia: estaciones principales (coordenadas aproximadas, lista PARCIAL).
BASIC_STATIONS = [
    ("60000", "Madrid Puerta de Atocha", 40.4065, -3.6894), ("17000", "Madrid Chamartín", 40.4722, -3.6829),
    ("71801", "Barcelona Sants", 41.3791, 2.1400), ("03216", "València Joaquín Sorolla", 39.4590, -0.3770),
    ("65000", "València Nord", 39.4666, -0.3774), ("51003", "Sevilla Santa Justa", 37.3922, -5.9755),
    ("54413", "Málaga María Zambrano", 36.7114, -4.4325), ("50500", "Córdoba Central", 37.8918, -4.7905),
    ("04040", "Zaragoza Delicias", 41.6587, -0.9112), ("60911", "Alicante Terminal", 38.3452, -0.4966),
    ("08223", "Vigo Urzáiz", 42.2380, -8.7132), ("31412", "A Coruña", 43.3533, -8.4093),
    ("15100", "León", 42.5946, -5.5804), ("15211", "Oviedo", 43.3547, -5.8523),
    ("11511", "San Sebastián", 43.3051, -1.9860), ("60600", "Albacete Los Llanos", 38.9999, -1.8567),
    ("03208", "Cuenca Fernando Zóbel", 39.9951, -2.1288), ("04007", "Guadalajara Yebes", 40.6893, -3.0996),
    ("08004", "Segovia Guiomar", 40.9068, -4.1019), ("04104", "Camp de Tarragona", 41.1888, 1.1418),
    ("04307", "Figueres Vilafant", 42.2637, 2.9452), ("", "Valladolid Campo Grande", 41.6425, -4.7267),
    ("", "Bilbao Abando", 43.2608, -2.9292), ("", "Santiago de Compostela", 42.8667, -8.5334),
    ("", "Pamplona", 42.8113, -1.6487), ("", "Granada", 37.1861, -3.6081), ("", "Burgos Rosa Manzano", 42.3568, -3.6226),
    ("", "Salamanca", 40.9515, -5.6697), ("", "Murcia del Carmen", 37.9844, -1.1297), ("", "Cartagena", 37.5990, -0.9760),
    ("", "Almería", 36.8411, -2.4580), ("", "Huelva", 37.2570, -6.9396), ("", "Cádiz", 36.5303, -6.2917),
    ("", "Jerez de la Frontera", 36.6881, -6.1288), ("", "Badajoz", 38.8788, -6.9694), ("", "Cáceres", 39.4619, -6.3722),
    ("", "Toledo", 39.8636, -4.0197), ("", "Ciudad Real", 38.9830, -3.9253), ("", "Puertollano", 38.6853, -4.1004),
    ("", "Lleida Pirineus", 41.6086, 0.6322), ("", "Girona", 41.9793, 2.8180), ("", "Huesca", 42.1342, -0.4090),
    ("", "Logroño", 42.4672, -2.4442), ("", "Vitoria-Gasteiz", 42.8446, -2.6850), ("", "Santander", 43.4613, -3.8153),
    ("", "Gijón Sanz Crespo", 43.5426, -5.6620), ("", "Lugo", 43.0068, -7.5561), ("", "Ourense", 42.3547, -7.8586),
    ("", "Pontevedra", 42.4326, -8.6413)]


def basic_stations():
    return [{"code": c, "n": n, "prov": "", "lat": la, "lon": lo} for c, n, la, lo in BASIC_STATIONS]


MAX_BYTES = 40 * 1024 * 1024    # tope por descarga (evita agotar la memoria con respuestas gigantes)


def read_capped(resp, max_bytes=MAX_BYTES):
    """Lee el cuerpo de una respuesta con tope de tamaño (acepta también objetos simples con .content)."""
    n = to_float((getattr(resp, "headers", None) or {}).get("Content-Length")) or 0
    if n > max_bytes:
        raise ValueError("respuesta demasiado grande")
    if hasattr(resp, "iter_content"):
        buf = bytearray()
        for chunk in resp.iter_content(65536):
            buf += chunk
            if len(buf) > max_bytes:
                resp.close()
                raise ValueError("respuesta demasiado grande")
        return bytes(buf)
    return resp.content


def valid_http_url(u):
    from urllib.parse import urlparse
    try:
        p = urlparse(str(u).strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def valid_topic(t):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(t).strip()))


def decode_text(content):
    """bytes -> texto probando las codificaciones habituales (utf-8, utf-16 con BOM, cp1252, latin-1)."""
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return content.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("latin-1", "ignore")


def _num(v):
    f = to_float(v)
    if f is None and isinstance(v, str):
        f = to_float(v.strip().replace(",", "."))
    return f


def _guess_stations_from_rows(text, delim):
    """Plan B: detecta columnas por sus valores (lat 27-44,5; lon -19..5,5 con decimales; código de 4-6 dígitos)."""
    import csv
    import re
    out = []
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        cells = [c.strip() for c in row]
        dec = [(_num(c), c) for c in cells if c and ("." in c or ",") and re.fullmatch(r"-?\d+[.,]\d+", c)]
        lat = next((v for v, _ in dec if v is not None and 27.0 <= v <= 44.5), None)
        lon = next((v for v, _ in dec if v is not None and -19.0 <= v <= 5.5), None)
        if lat is None or lon is None:
            continue
        name = next((c for c in cells if re.search(r"[A-Za-zÁÉÍÓÚÜáéíóúüÑñ]", c) and not re.fullmatch(r"-?\d+[.,]\d+", c)), "")
        code = next((c for c in cells if c.isdigit() and 4 <= len(c) <= 6), "")
        out.append({"code": norm_code(code), "n": name, "prov": "", "lat": lat, "lon": lon})
    return out


def parse_stations_csv(text):
    """CSV con cabecera (separador ; , o tab; decimales con coma): lat/lon y opcionalmente código, nombre, provincia."""
    import csv
    text = (text or "").lstrip("\ufeff")
    head = text.splitlines()[0] if text else ""
    delim = "\t" if "\t" in head else (";" if head.count(";") >= head.count(",") and ";" in head else ",")
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        r = {norm_text(k).lower(): v for k, v in r.items() if k}
        lat = _num(pick(r, ["latitud", "lat", "latitude"]))
        lon = _num(pick(r, ["longitud", "lon", "lng", "longitude"]))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        out.append({"code": norm_code(pick(r, ["codigo", "cod estacion", "codigo estacion", "cod", "code", "stop id", "id"])),
                    "n": str(pick(r, ["descripcion", "nombre", "name", "nombre estacion", "estacion"]) or "").strip(),
                    "prov": str(pick(r, ["provincia", "prov", "province"]) or "").strip(), "lat": lat, "lon": lon})
    return out or _guess_stations_from_rows(text, delim)


def save_stations_cache(stations):
    try:
        with open(STATIONS_CACHE, "w", encoding="utf-8") as f:
            json.dump(stations, f)
        os.chmod(STATIONS_CACHE, 0o600)
    except OSError:
        pass


def load_stations_cache():
    try:
        with open(STATIONS_CACHE, encoding="utf-8") as f:
            return [x for x in json.load(f) if isinstance(x, dict) and "lat" in x and "lon" in x]
    except (OSError, ValueError, TypeError):
        return []


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


CAUSAS = [
    ("Accidente / persona en la vía", ("atropell", "persona en la v", "persona en vi", "accidente", "arrollad", "colisi", "descarril")),
    ("Incendio", ("incendio", "fuego", "humo")),
    ("Meteorología", ("lluvia", "temporal", "inunda", "dana", "viento", "nieve", "tormenta", "meteorol", "aemet", "desprendimiento", "riada")),
    ("Seguridad / vandalismo", ("robo", "vandal", "sabotaje", "intrusi", "cable robado")),
    ("Infraestructura", ("infraestructura", "catenaria", "senaliz", "aguja", "paso a nivel", "electrific", "suministro", "tension", "averia en la via",
                         "incidencia en la via", "via ", "via.")),
    ("Material rodante", ("averia del tren", "averia en el tren", "tren averiado", "material rodante", "averia tecnica")),
    ("Obras / mantenimiento", ("obras", "mantenimiento", "trabajos", "actuacion programada", "corte programado")),
    ("Personal / huelga", ("huelga", "servicios minimos", "falta de personal", "paro ")),
]


def classify_cause(text):
    """Causa deducida del propio texto del aviso; si no la dice: 'Motivo no comunicado'."""
    t = "".join(c for c in unicodedata.normalize("NFD", str(text or "").lower()) if unicodedata.category(c) != "Mn")
    for name, keys in CAUSAS:
        if any(k in t for k in keys):
            return name
    return "Motivo no comunicado"


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
                    "pts": parse_tramo(pick(it, ["tramo", "puntos", "geometry"])),
                    "causa": classify_cause(f"{title} {text}")})
    return out


_STOP_KEYS = ["estaciones", "paradas", "stops", "recorrido", "ruta", "listaEstaciones", "itinerario"]
_CODE_KEYS = ["codEstacion", "codigoEstacion", "codEst", "codigo", "cod", "estacion", "id", "stationCode"]
_TIME_KEYS = ["horaLlegada", "horaLlegadaPlanificada", "horaProgramada", "horaPrevista", "horaPaso", "hora",
              "llegada", "horaSalida", "salida", "horaEstimada", "time"]


def _hhmm(v):
    """'2026-10-31T21:40:00' o '21:40' -> '21:40' ('' si no es una hora). Solo dígitos: seguro para HTML."""
    m = re.search(r"(?:^|[T ])([01]\d|2[0-3]):([0-5]\d)", str(v or ""))
    return f"{m.group(1)}:{m.group(2)}" if m else ""


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
        try:
            os.chmod(DB_PATH, 0o600)      # el historial de alertas es privado
        except OSError:
            pass
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
        recent = _db_query("SELECT id FROM incidentes WHERE kind=? AND ref=? AND resolved_ts IS NOT NULL AND resolved_ts >= ? "
                           "AND confirmed != -1 ORDER BY resolved_ts DESC LIMIT 1", (kind, ref, now - 600))
        if len(recent):    # el aviso "rebotó" en menos de 10 min: es el mismo incidente, no uno nuevo
            _db_run("UPDATE incidentes SET resolved_ts=NULL, last_ts=?, msg=?, lat=?, lon=? WHERE id=?",
                    (now, msg, lat, lon, int(recent["id"].iloc[0])))
        else:
            _db_run("INSERT INTO incidentes (kind, ref, first_ts, last_ts, resolved_ts, lat, lon, msg, severity, confirmed) "
                    "VALUES (?,?,?,?,NULL,?,?,?,?,0)", (kind, ref, now, now, lat, lon, msg, severity))


def db_clear_incidents():
    _db_run("DELETE FROM incidentes")
    _db_run("DELETE FROM eventos")


def db_event_counts(hours=24):
    df = _db_query("SELECT nivel, clave, COUNT(*) AS n FROM eventos WHERE ts >= ? AND fase='nuevo' "
                   "GROUP BY nivel, clave ORDER BY n DESC LIMIT 500", (time.time() - hours * 3600,))
    return df if not df.empty else pd.DataFrame(columns=["nivel", "clave", "n"])


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
                   (str(name)[:200], json.dumps([[a, b] for a, b in pts[:500]]), time.time(), expires_ts, source, str(note)[:500], ref))


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

            tm0 = to_float(t.get("time"))
            if tm0 is not None and tm0 > 1e11:
                tm0 /= 1000.0
            prev = prev_state.get(t_id)
            speed, inst, state_speed = 0.0, None, None
            heading, has_heading, slow_since = 0.0, False, None
            prev_inst, decel = None, 0.0

            if prev:
                heading, has_heading = prev["heading"], prev["has_heading"]
                gps_dt = (tm0 - prev["gps_t"]) if (tm0 is not None and prev.get("gps_t") is not None) else None
                dt = gps_dt if gps_dt is not None else fetched_at - prev["ts"]   # dt real entre muestras GPS
                if gps_dt is not None and gps_dt <= 0 and not t_id.startswith("SIM-"):
                    compared += 1                      # sin muestra nueva: cuenta para detectar feed congelado
                if dt >= 1:
                    dist = haversine(prev["lat"], prev["lon"], lat, lon)
                    if not t_id.startswith("SIM-"):
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
                               "heading": heading, "has_heading": has_heading, "slow_since": slow_since,
                               "gps_t": tm0 if tm0 is not None else (prev or {}).get("gps_t")}

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
                "grupo": grupo_de(cod_key), "cod_prod": cod_key, "src": t.get("_src", "LD"),
                "status": t.get("_status", ""), "delay_known": bool(t.get("_delay_known", True)),
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
            sim_rows = [r for r in rows if str(r["cod_comercial"]).startswith("SIM-")]
            if sim_rows:      # el tren de prueba sigue su propio ritmo aunque el feed real no cambie
                keep = self.last_df[~self.last_df["cod_comercial"].astype(str).str.startswith("SIM-")]
                self.last_df = pd.concat([keep, pd.DataFrame(sim_rows, columns=BASE_COLUMNS)], ignore_index=True)
                self.state.update({k: v for k, v in new_state.items() if k.startswith("SIM-")})
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
    known = cfg.get("stations_known", True)   # sin estaciones cargadas NO se puede descartar "en estación": se alarma
    far = (dist.notna() & (dist > cfg["station_radius_m"]) & fresh) if known else fresh
    far = far & ~df["status"].fillna("").isin(["STOPPED_AT", "INCOMING_AT"])   # Cercanías: "en estación" según el feed
    far = far & ~((df["est_ant"].astype(str) != "") & (df["est_ant"] == df["est_sig"]))  # larga distancia: "En <estación>"
    sf = df["stopped_for_s"]
    mult = df["src"].map({"CERC": cfg.get("cerc_stop_mult", 3)}).fillna(1.0)    # Cercanías: más prudencia
    df["is_stopped"] = ((sf >= cfg["min_stop_s"] * mult) & far).astype(bool)
    df["is_suspect"] = ((sf >= cfg["early_stop_s"] * mult) & (sf < cfg["min_stop_s"] * mult) & far).astype(bool)

    cand = ((df["prev_inst_kmh"] >= cfg["brake_min_kmh"]) & (df["decel_ms2"] >= cfg["brake_ms2"])
            & ((dist.notna() & (dist > cfg["brake_station_m"])) if known else True) & fresh & (df["src"] == "LD"))
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
                & (df["speed_kmh"] > max(1, cfg["risk_min_kmh"])) & (df["has_heading"] == True)  # noqa: E712
                & (df["src"] == "LD")]
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
    if df.empty or not cfg.get("stations_known", True):   # sin estaciones fiables NO se declara ningún accidente
        return out
    targets = {a["stopped"] for a in risk_alerts}
    for _, s in df[df["is_stopped"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        if cod in dismissed:
            continue
        why = []
        if bool(s["braking"]):
            why.append("frenada brusca previa")
        limit = cfg.get("accident_s", 600) * (cfg.get("cerc_stop_mult", 3) if str(s["src"]) == "CERC" else 1)
        if s["stopped_for_s"] >= limit:
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
                & (df["has_heading"] == True) & (df["src"] == "LD")]  # noqa: E712
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


def check_close_following(df, cfg):
    """
    Seguidor que se acerca por detrás a un tren MÁS LENTO que va delante (mismo sentido y casi misma línea).
    Avisa por tiempo hasta alcance y por distancia de frenado: aunque el de delante no esté parado (p. ej. a 33 km/h).
    Heurística: sin la topología real de la vía (desvíos, vías paralelas) puede dar falsos avisos.
    """
    out = []
    if df.empty or not cfg.get("close_on", True):
        return out
    age = pd.to_numeric(df["gps_age_s"], errors="coerce")
    ok = df[(df["has_heading"] == True) & (df["speed_kmh"] > SLOW_KMH) & ~(age > cfg.get("gps_stale_s", 600))  # noqa: E712
            & (df["src"] == "LD")]
    if len(ok) < 2:
        return out
    lat, lon = ok["lat"].to_numpy(float), ok["lon"].to_numpy(float)
    hd, sp = ok["heading"].to_numpy(float), ok["speed_kmh"].to_numpy(float)
    cod, tipo = ok["cod_comercial"].tolist(), ok["tipo"].tolist()
    kx = math.cos(math.radians(float(lat.mean())))
    x, y = (lon - lon.mean()) * kx * 111320.0, (lat - lat.mean()) * 110540.0
    a_srv = max(0.1, float(cfg.get("close_decel", 0.6)))
    for i in range(len(ok)):                       # i = seguidor
        dx, dy = x - x[i], y - y[i]
        d = np.hypot(dx, dy)
        brg = (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0
        da = np.abs((brg - hd[i] + 180.0) % 360.0 - 180.0)        # ¿está delante del seguidor?
        dh = np.abs((hd - hd[i] + 180.0) % 360.0 - 180.0)         # ¿mismo sentido?
        cross = d * np.sin(np.radians(da))                        # desvío lateral
        m = ((d > 20) & (d < cfg["close_gap_m"]) & (da < 45) & (dh < cfg["close_heading_deg"])
             & (cross <= cfg["close_lateral_m"]) & (sp[i] - sp > cfg["close_closing_kmh"]))
        m[i] = False
        if not m.any():
            continue
        j = int(np.where(m)[0][np.argmin(d[m])])                  # el tren de delante más cercano
        vf, vl = sp[i] / 3.6, sp[j] / 3.6
        gap, closing = float(d[j]), vf - vl
        ttc = gap / closing
        brake = max(0.0, vf * vf - vl * vl) / (2 * a_srv)          # distancia necesaria para igualar su velocidad
        if ttc <= cfg["close_ttc_s"] or gap <= brake * 1.5:
            out.append({"follower": cod[i], "leader": cod[j], "tipo": tipo[i], "gap_m": round(gap),
                        "v_f": round(float(sp[i])), "v_l": round(float(sp[j])), "closing_kmh": round(closing * 3.6),
                        "ttc_s": round(ttc), "brake_m": round(brake), "critical": bool(gap <= brake or ttc <= 60),
                        "lat": float(lat[j]), "lon": float(lon[j])})
    out.sort(key=lambda a: a["ttc_s"])
    return out


def compute_risk(df, risk_alerts, cut_alerts, acc, cfg, close=()):
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
    for a in close:
        urg = max(0.0, 1 - a["ttc_s"] / max(1, cfg.get("close_ttc_s", 150)))
        bump(a["follower"], int((65 if a["critical"] else 40) + 25 * urg), "APROXIMACIÓN")
        bump(a["leader"], 10, "TIENE TREN DETRÁS")
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
    close = check_close_following(df, cfg)
    overflow = 0
    if len(acc) > cfg.get("accident_max", 2):      # 3+ accidentes a la vez no es plausible: es un fallo de datos/calibración
        overflow, acc = len(acc), []
    return {"risk": risk, "acc": acc, "cut": cut, "close": close, "acc_overflow": overflow,
            "scores": compute_risk(df, risk, cut, acc, cfg, close)}


def make_event(kind, key, msg, speak=None, lat=None, lon=None, subject=None):
    return {"kind": kind, "key": key, "msg": msg, "speak": speak or msg,
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None, "subject": subject or msg}


def _brief(s, info):
    """(ruta, dónde) legibles de una fila de tren."""
    info = info or {}
    ruta = (f"{label_est(s['origen'], info)} → {label_est(s['destino'], info)}"
            if (s["origen"] or s["destino"]) else "ruta desconocida")
    w = where_text(s["est_ant"], s["est_sig"], info)
    where = (w[0].lower() + w[1:]) if w else "tramo desconocido"
    return ruta, where


def _dist_txt(s):
    d = to_float(s["dist_to_station"])
    return f"a {int(round(d))} m de la estación más cercana" if d is not None else \
        "sin dato de estaciones (no se puede descartar que esté en una estación)"


def build_events(df, risk_alerts, cut_alerts=(), accidents=(), info=None, close_alerts=(), acc_overflow=0):
    events = []
    info = info or {}
    if acc_overflow:
        events.append(make_event(
            "system", "sys|plaus",
            f"{acc_overflow} candidatos a accidente a la vez: se DESCARTAN por plausibilidad (más de lo razonable). Probable "
            "fallo de datos o calibración demasiado sensible: revisa estaciones y parámetros en CALIBRAR.",
            speak="Demasiados candidatos a accidente a la vez, descartados por plausibilidad", subject="Plausibilidad de accidentes"))
    if df.empty:
        return events
    for _, s in df[df["is_stopped"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        ruta, where = _brief(s, info)
        events.append(make_event(
            "stopped", f"stopped|{cod}",
            f"DETENIDO EN VÍA · Tren {cod} ({s['tipo']}, {ruta}) · {where} · parado {mmss(s['stopped_for_s'])} a "
            f"{s['speed_kmh']:.0f} km/h · {_dist_txt(s)} · retraso {int(s['retraso_min'])} min · "
            f"posición {s['lat']:.4f}, {s['lon']:.4f}.",
            speak=f"Tren {cod} detenido en vía, {where}", lat=s["lat"], lon=s["lon"], subject=f"Tren {cod} detenido en vía"))
    for _, s in df[df["is_suspect"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        ruta, where = _brief(s, info)
        events.append(make_event(
            "early", f"early|{cod}",
            f"AVISO TEMPRANO · Tren {cod} ({s['tipo']}, {ruta}) · {where} · {mmss(s['stopped_for_s'])} a baja velocidad "
            f"({s['speed_kmh']:.0f} km/h) · {_dist_txt(s)} · retraso {int(s['retraso_min'])} min.",
            speak=f"Aviso temprano. Tren {cod} posiblemente detenido", lat=s["lat"], lon=s["lon"],
            subject=f"Tren {cod} posible detención"))
    for _, s in df[df["braking"] == True].iterrows():  # noqa: E712
        cod = s["cod_comercial"]
        ruta, where = _brief(s, info)
        events.append(make_event(
            "brake", f"brake|{cod}",
            f"FRENADA BRUSCA · Tren {cod} ({s['tipo']}, {ruta}) · {where} · de {s['prev_inst_kmh']:.0f} a "
            f"{s['inst_kmh']:.0f} km/h ({s['decel_ms2']:.2f} m/s²) · {_dist_txt(s)}.",
            speak=f"Frenada brusca del tren {cod}", lat=s["lat"], lon=s["lon"], subject=f"Tren {cod} frenada brusca"))
    for a in close_alerts:
        crit = a["critical"]
        events.append(make_event(
            "risk" if crit else "close", f"{'closecrit' if crit else 'close'}|{a['follower']}|{a['leader']}",
            f"{'NO LLEGA A FRENAR' if crit else 'APROXIMACIÓN'} · Tren {a['follower']} ({a['tipo']}, {a['v_f']} km/h) se acerca "
            f"por detrás al tren {a['leader']} ({a['v_l']} km/h): hueco {a['gap_m']} m, cierre {a['closing_kmh']} km/h, "
            f"alcance en {a['ttc_s']} s; necesita {a['brake_m']} m para igualar su velocidad.",
            speak=f"{'Peligro. ' if crit else 'Atención. '}Tren {a['follower']} se aproxima al tren {a['leader']}. "
                  f"{a['ttc_s']} segundos.",
            lat=a["lat"], lon=a["lon"], subject=f"Tren {a['follower']} aproximándose a {a['leader']}"))
    for a in risk_alerts:
        events.append(make_event(
            "risk", f"risk|{a['moving']}|{a['stopped']}",
            f"RIESGO CRÍTICO · Tren {a['moving']} ({a['speed_kmh']} km/h) se acerca al tren {a['stopped']} detenido: "
            f"{a['dist_m']} m, TTC {a['ttc_s']} s.",
            speak=f"Riesgo crítico. Tren {a['moving']} se acerca al tren {a['stopped']} detenido. {a['ttc_s']} segundos.",
            lat=a["lat"], lon=a["lon"], subject=f"Riesgo {a['moving']} hacia {a['stopped']}"))
    for a in cut_alerts:
        events.append(make_event(
            "risk", f"cutrisk|{a['moving']}|{a['cut_id']}",
            f"TRAMO CORTADO · Tren {a['moving']} ({a['speed_kmh']} km/h) se dirige al tramo «{a['cut_name']}»: "
            f"{a['dist_m']} m, TTC {a['ttc_s']} s.",
            speak=f"Atención. Tren {a['moving']} se dirige a un tramo cortado. {a['ttc_s']} segundos.",
            lat=a["lat"], lon=a["lon"], subject=f"Tren {a['moving']} hacia tramo cortado"))
    for a in accidents:
        row = df[df["cod_comercial"] == a["cod"]]
        extra = ""
        if not row.empty:
            ruta, where = _brief(row.iloc[0], info)
            extra = f" ({ruta}, {where}, {a['lat']:.4f}, {a['lon']:.4f})"
        events.append(make_event(
            "accident", f"accident|{a['cod']}",
            f"POSIBLE ACCIDENTE · Tren {a['cod']} ({a['tipo']}){extra} detenido en vía — {', '.join(a['why'])}.",
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


NTFY_PRIORITY = {"close": 4, "accident": 5, "risk": 5, "stopped": 4, "brake": 3, "early": 3, "system": 2, "resolved": 2}
NTFY_TAGS = {"close": "zap,train", "accident": "boom,rotating_light,train", "risk": "rotating_light,train", "stopped": "red_circle,train", "brake": "warning,train",
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
def _claim_instance():
    """Evita que DOS copias del programa envíen avisos duplicados. Devuelve el PID de la otra copia viva (o None)."""
    path = os.getenv("EBM_LOCK", "ebm_monitor.pid")
    me = os.getpid()
    try:
        if os.name == "posix" and os.path.exists(path):
            with open(path) as f:
                old = int((f.read() or "0").strip() or 0)
            if old and old != me:
                try:
                    os.kill(old, 0)
                    return old
                except ProcessLookupError:
                    pass
                except PermissionError:
                    return old
                except OSError:
                    pass
        with open(path, "w") as f:
            f.write(str(me))

        def _release():
            try:
                with open(path) as f:
                    if (f.read() or "").strip() == str(me):
                        os.remove(path)
            except OSError:
                pass
        atexit.register(_release)
    except (OSError, ValueError):
        pass
    return None


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
                              ("Estaciones CSV Renfe", RENFE_STATIONS_CSV_URLS[0], None), ("Estaciones", URL_ESTACIONES, None),
                              ("Rutas y horarios", URL_RUTAS, None),
                              ("Cercanías (posiciones)", URL_CERC_POS, None), ("Cercanías (retrasos)", URL_CERC_TRIPS, None),
                              ("Avisos oficiales", URL_CERC_ALERTS, None)):
        t0 = time.time()
        try:
            r = requests.get(url, params=params, timeout=10, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
            ms = int((time.time() - t0) * 1000)
            if r.status_code != 200:
                out.append((name, False, f"HTTP {r.status_code} en {ms} ms"))
                continue
            body = read_capped(r)
            if name.startswith("Estaciones CSV"):
                txt = decode_text(body)
                est = parse_stations_csv(txt)
                out.append((name, bool(est), f"HTTP 200 en {ms} ms · {len(body)} bytes · {len(est)} estaciones leídas · "
                                             f"inicio del archivo: {txt[:110]!r}"))
                continue
            data = json.loads(body)
            if name.startswith(("Cercanías", "Avisos")):
                n = len(data.get("entity", []) or []) if isinstance(data, dict) else 0
                out.append((name, n > 0, f"HTTP 200 en {ms} ms · {n} entidades"))
                continue
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


INCIDENT_KINDS = ("brake", "stopped", "risk", "accident", "close")
SEVERITY = {"brake": 1, "stopped": 2, "close": 2, "risk": 3, "accident": 4}
SIM_ID = "SIM-001"


def _is_sim(ev):
    """Eventos del tren de simulacro: nunca se envían a canales ni se guardan en la memoria de 30 días."""
    k = ev.get("key", "")
    return "SIM-" in k or k.endswith("|sim_cut")


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
        self.cerc_cache, self.cerc_ts, self.cerc_ok_ts, self.cerc_error = None, 0.0, 0.0, None
        self.trips, self.trips_error = {}, None
        self.alerts, self.alerts_error, self.alerts_ts = [], None, 0.0
        self.stations_error = None
        self.stations_source = None
        self._stations_busy = False
        self.sim = {"active": False, "lat": 38.30, "lon": -4.20, "heading": 0.0, "speed": 0.0, "target": 0.0,
                    "decel": 0.8, "delay": 0, "ts": None, "trail": []}
        self.sim_cut = None
        self.no_autocut = set()          # accidentes cuyo tramo el usuario ya reabrió
        self.stations_base = []          # descargadas (Renfe CSV / GTFS / OSM / caché / lista básica)
        self.learned = {}                # código -> (lat, lon) aprendidas del propio feed (tren "EN estación")
        self._learned_saved = 0
        self.push_times = deque()
        self.push_suppressed, self.push_sum_ts = 0, 0.0
        self.push_enabled, self.user_stopped = True, False
        self.secondary, self.primary_pid = False, None
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
        if not demo:
            self.primary_pid = _claim_instance()
            self.secondary = bool(self.primary_pid)

    # ---- ciclo de vida ----
    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_flag.clear()
            self.thread = threading.Thread(target=self._loop, name="ebm-monitor", daemon=True)
            self.thread.start()

    def ensure_running(self):
        if self.user_stopped:
            return
        if self.thread is None or not self.thread.is_alive():
            self.start()

    def stop(self):
        self.stop_flag.set()
        self.wake.set()

    def stop_user(self):
        """El usuario detiene el monitor: no se sondea ni se envía NADA hasta que lo reanude."""
        self.user_stopped = True
        self.stop()

    def resume_user(self):
        self.user_stopped = False
        self.stop_flag.clear()
        self.start()

    def set_push(self, on):
        self.push_enabled = bool(on)

    def _can_push(self, e):
        """Envío externo permitido: canales, interruptor, instancia principal, no demo/simulacro y límite anti-saturación."""
        if not (self.channels and self.push_enabled and not self.secondary and not self.demo and not _is_sim(e)):
            return False
        if not should_push(e, self.cfg):
            return False
        now = time.time()
        while self.push_times and now - self.push_times[0] > 300:
            self.push_times.popleft()
        if len(self.push_times) >= (15 if e["kind"] in ("accident", "risk") else 6):
            self.push_suppressed += 1
            return False
        self.push_times.append(now)
        return True

    def _flood_summary(self):
        now = time.time()
        if (self.push_suppressed and now - self.push_sum_ts > 300 and self.channels and self.push_enabled
                and not self.secondary and not self.demo):
            ev = make_event("system", "sys|flood", f"{self.push_suppressed} avisos más NO se enviaron "
                                                   "(límite anti-saturación: máx. 6 cada 5 min).")
            ev.update(seq=0, ts=now, hora=datetime.now(TZ).strftime("%H:%M:%S"), phase="resumen")
            self.push_suppressed, self.push_sum_ts = 0, now
            self.pool.submit(self._deliver, ev)

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
                if not (v and str(v).strip()):
                    continue
                v = str(v).strip()
                if k in ("adif_url", "webhook_url", "ntfy_server") and not valid_http_url(v):
                    continue
                if k == "ntfy_topic" and not valid_topic(v):
                    continue
                self.channels[k] = v

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
            self.stations_base = list(stations)
            self._rebuild_stations()
            self.stations_ts = time.time()

    def _rebuild_stations(self):
        base_codes = {x.get("code") for x in self.stations_base if x.get("code")}
        learned = [{"code": c, "n": "", "prov": "", "lat": la, "lon": lo, "learned": True}
                   for c, (la, lo) in self.learned.items() if c not in base_codes]
        self.stations = list(self.stations_base) + learned
        info = {x["code"]: x for x in learned}
        info.update({x["code"]: x for x in self.stations_base if x.get("code")})
        self.station_info = info
        self.stations_arr = np.array([[x["lat"], x["lon"]] for x in self.stations], dtype=float) \
            if self.stations else np.empty((0, 2))

    def _learn_stations(self, df):
        """Aprende coordenadas de estaciones del propio feed: tren 'EN estación' (larga distancia) o STOPPED/INCOMING (Cercanías)."""
        if df.empty:
            return
        same = (df["est_ant"].astype(str) != "") & (df["est_ant"] == df["est_sig"])
        at = df[(same & (df["speed_kmh"] < 40)) | df["status"].isin(["STOPPED_AT", "INCOMING_AT"])]
        base_codes = {x.get("code") for x in self.stations_base}
        new = 0
        for _, r in at.iterrows():
            code = r["est_sig"] or r["est_ant"]
            if code and code not in self.learned and code not in base_codes:
                self.learned[code] = (float(r["lat"]), float(r["lon"]))
                new += 1
        if new:
            self._rebuild_stations()
            if len(self.learned) - self._learned_saved >= 20:
                self._learned_saved = len(self.learned)
                save_stations_cache(self.stations)

    def has_stations(self):
        return len(self.stations) > 0

    # ---- tramos cortados ----
    def all_cuts(self):
        with self.lock:
            return list(self.cuts) + list(self.adif_cuts) + ([self.sim_cut] if self.sim_cut else [])

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
        """Reabre un tramo. Si era automático (accidente activo) NO se vuelve a cortar solo hasta que el accidente termine."""
        with self.lock:
            cut = next((c for c in self.all_cuts() if str(c["id"]) == str(cut_id)), None)
            kind, _, cod = str((cut or {}).get("ref") or "").partition("|")
            if kind in ("auto", "acc") and cod:
                self.no_autocut.add(cod)
            if str(cut_id) == "sim_cut":
                self.sim_cut = None
                self.no_autocut.add(SIM_ID)
                return True
            if str(cut_id).startswith("demo"):
                self.cuts = [c for c in self.cuts if str(c["id"]) != str(cut_id)]
                return True
            try:
                db_cut_close(int(cut_id), time.time())
            except (TypeError, ValueError):
                return False
            self.reload_cuts()
            return True

    def _train_row(self, cod):
        df = self.tracker.last_df
        m = df[df["cod_comercial"] == cod] if not df.empty else df
        return None if m.empty else m.iloc[0]

    def cut_from_train(self, cod):
        if str(cod).startswith("SIM-"):
            return None
        with self.lock:
            row = self._train_row(cod)
            if row is None:
                return None
            pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
            return name if self.add_cut(name, pts, None, "Cierre manual desde el tren", "manual", f"man|{cod}") else None

    def confirm_accident(self, cod):
        if str(cod).startswith("SIM-"):
            return False
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
        if str(cod).startswith("SIM-"):
            with self.lock:
                self.dismissed.add(cod)
            return True
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
        r = self.http.get(url, params=params, timeout=10, stream=True)
        r.raise_for_status()
        return json.loads(read_capped(r))

    # ---- estaciones ----
    def _ensure_stations(self, now):
        if self._stations_busy:
            return
        if self.stations_base and (now - self.stations_ts) <= 3600:
            return
        if (now - self.stations_try_ts) < 60:
            return
        self.stations_try_ts = now
        if not self.stations_base:
            cached = load_stations_cache()
            if cached:
                self.set_stations(cached)
                self.stations_source = "copia guardada"
        self._stations_busy = True
        self.pool.submit(self._stations_job)

    def _stations_job(self):
        try:
            errors, found, sources = [], [], []
            steps = (("Renfe (CSV)", self._stations_csv), ("Renfe", self._stations_renfe),
                     ("GTFS Renfe", self._stations_gtfs), ("OpenStreetMap", self._stations_osm))
            for name, fetch in steps:
                if len(found) >= 300:        # con 300+ estaciones ya hay cobertura suficiente
                    break
                try:
                    est = fetch()
                except Exception as e:  # noqa: BLE001 - un formato inesperado no puede matar el hilo de estaciones
                    errors.append(f"{name}: {safe_error(e)}")
                    continue
                if est:
                    found += est
                    sources.append(name)
                else:
                    errors.append(f"{name}: sin estaciones")
            if found:
                uniq = {(x["code"], round(x["lat"], 4), round(x["lon"], 4)): x for x in found}
                est = list(uniq.values())
                self.set_stations(est)
                save_stations_cache(est)
                with self.lock:
                    self.stations_error = " · ".join(errors) or None
                    self.stations_source = " + ".join(sources)
                print(f"[EBM] estaciones cargadas: {len(est)} ({' + '.join(sources)})" + (f" · avisos: {errors}" if errors else ""), flush=True)
                return
            print(f"[EBM] NO se pudieron descargar estaciones: {errors}", flush=True)
            if not self.stations_base:     # nada descargado y sin copia: lista básica parcial para no ir a ciegas
                self.set_stations(basic_stations())
                with self.lock:
                    self.stations_source = "lista básica PARCIAL integrada (principales estaciones)"
            with self.lock:
                self.stations_error = " · ".join(errors) + (" · usando copia guardada o lista básica" if self.stations else "")
                if self.stations_base:
                    self.stations_ts = time.time() - 3000   # reintentar en ~10 min
        finally:
            self._stations_busy = False

    def _stations_csv(self):
        last = None
        for url in RENFE_STATIONS_CSV_URLS:
            try:
                r = self.http.get(url, timeout=60, stream=True)
                r.raise_for_status()
                est = parse_stations_csv(decode_text(read_capped(r)))
                if est:
                    return est
            except requests.RequestException as e:
                last = e
        if last:
            raise last
        return []

    def _stations_gtfs(self):
        out, last = [], None
        for url in GTFS_URLS:
            try:
                r = self.http.get(url, timeout=120, stream=True)
                r.raise_for_status()
                out += parse_gtfs_stops_zip(read_capped(r))
            except (requests.RequestException, OSError, zipfile.BadZipFile) as e:
                last = e
        if not out and last:
            raise last
        return out

    def _stations_renfe(self):
        return parse_stations(self._get_json(URL_ESTACIONES))

    def _stations_osm(self):
        last = None
        for url in OVERPASS_URLS:
            try:
                r = self.http.post(url, data={"data": OVERPASS_QUERY}, timeout=100, stream=True)
                r.raise_for_status()
                est = parse_overpass(json.loads(read_capped(r)))
                if est:
                    return est
            except (requests.RequestException, ValueError) as e:
                last = e
        if last:
            raise last
        return []

    # ---- red completa: Cercanías / Rodalies / Tram (GTFS-RT) ----
    def _cerc_delays(self, now):
        try:
            self.trips = parse_gtfsrt_delays(self._get_json(URL_CERC_TRIPS))
            self.trips_error = None
        except (requests.RequestException, ValueError) as e:
            self.trips_error = safe_error(e)
        return self.trips

    def _cercanias(self, now):
        if self.demo:
            return []
        if self.cerc_cache is not None and (now - self.cerc_ts) < 20:
            return self.cerc_cache
        self.cerc_ts = now
        try:
            veh = parse_gtfsrt_vehicles(self._get_json(URL_CERC_POS))
            delays = self._cerc_delays(now)
            for t in veh:
                d = delays.get(t["_trip"])
                if d is not None:
                    t["ultRetraso"], t["_delay_known"] = str(d), True
            for n_x, url_x in enumerate(EXTRA_POS_URLS):      # FGC, Euskotren… si publican GTFS-RT en JSON
                try:
                    extra = parse_gtfsrt_vehicles(self._get_json(url_x))
                    for t in extra:
                        t["codComercial"] = f"X{n_x + 1}:{t['codComercial']}"
                    veh += extra
                except (requests.RequestException, ValueError):
                    pass
            self.cerc_cache, self.cerc_ok_ts, self.cerc_error = veh, now, None
        except (requests.RequestException, ValueError) as e:
            self.cerc_error = safe_error(e)
            if self.cerc_cache is None or now - self.cerc_ok_ts > 120:
                self.cerc_cache = []
        return self.cerc_cache or []

    def _poll_alerts(self, now):
        if self.demo or (now - self.alerts_ts) < 120:
            return
        self.alerts_ts = now
        try:
            items = parse_gtfsrt_alerts(self._get_json(URL_CERC_ALERTS), now)
            with self.lock:
                self.alerts, self.alerts_error = items, None
        except (requests.RequestException, ValueError) as e:
            with self.lock:
                self.alerts_error = safe_error(e)

    # ---- simulacro (tren de prueba) ----
    def sim_set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                if k in self.sim:
                    self.sim[k] = v
            if self.sim["active"] and self.sim["ts"] is None:
                self.sim["ts"] = time.time()

    def sim_remove(self):
        with self.lock:
            self.sim.update(active=False, ts=None, speed=0.0, target=0.0, trail=[])
            self.sim_cut = None
            self.dismissed.discard(SIM_ID)

    def _sim_train(self, now):
        s_ = self.sim
        if not s_["active"]:
            return None
        dt = 0.0 if s_["ts"] is None else min(30.0, max(0.0, now - s_["ts"]))
        s_["ts"] = now
        if s_["speed"] < s_["target"]:
            s_["speed"] = min(s_["target"], s_["speed"] + 0.6 * 3.6 * dt)
        elif s_["speed"] > s_["target"]:
            s_["speed"] = max(s_["target"], s_["speed"] - s_["decel"] * 3.6 * dt)
        if dt > 0 and s_["speed"] > 0:
            s_["lat"], s_["lon"] = offset_point(s_["lat"], s_["lon"], s_["heading"], s_["speed"] / 3.6 * dt)
            s_["trail"] = (s_["trail"] + [(s_["lat"], s_["lon"])])[-80:]
        return {"codComercial": SIM_ID, "codProduct": 99, "latitud": s_["lat"], "longitud": s_["lon"],
                "ultRetraso": str(int(s_["delay"])), "time": int(now), "mat": "SIMULADO", "accesible": False}

    def tick(self):
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            now = time.time()
            if self.db_ok and now - self.last_purge > 6 * 3600:
                self.last_purge = now
                db_purge(now)
            self._ensure_stations(now)
            try:
                t0 = time.time()
                raw = demo_feed(now) if self.demo else self._get_json(URL_FLOTA, {"v": int(now * 1000)})
                self.latency_ms = int((time.time() - t0) * 1000)
                if not (isinstance(raw, dict) and "trenes" in raw):
                    raise ValueError("feed sin 'trenes'")
                try:
                    cerc = self._cercanias(now)
                except Exception as e:  # noqa: BLE001 - la red de Cercanías nunca debe impedir la lectura de larga distancia
                    cerc, self.cerc_error = [], f"{type(e).__name__} al leer Cercanías"
                if cerc:
                    raw = dict(raw, trenes=list(raw.get("trenes") or []) + cerc)
            except (requests.RequestException, ValueError) as e:
                with self.lock:
                    self.consecutive_errors += 1
                    self.last_error = type(e).__name__
                    self.last_error_detail = f"{type(e).__name__}: {str(e)[:160]}"
                    self._evaluate(time.time())
            else:
                self.ingest(raw, time.time())
            for poll in (self._poll_incidents, self._poll_alerts, self._poll_routes):
                try:
                    poll(time.time())
                except Exception as e:  # noqa: BLE001
                    with self.lock:
                        self.last_error_detail = f"{poll.__name__}: {type(e).__name__}"
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
            sim_t = self._sim_train(fetched_at)
            if sim_t is not None:
                raw = dict(raw, trenes=list(raw.get("trenes") or []) + [sim_t])
            self.tracker.update(raw, self.stations_arr, fetched_at)
            self.consecutive_errors = 0
            self.last_error = None
            self.last_tick = time.time()
            self._evaluate(fetched_at)

    # ---- evaluación y avisos ----
    def _sync_sim_cut(self, df, acc):
        """Tramo cortado del simulacro: solo en memoria (no toca la base de datos real)."""
        sim = [a for a in acc if str(a["cod"]).startswith("SIM-") and SIM_ID not in self.no_autocut]
        before = self.sim_cut is not None
        if sim:
            row = df[df["cod_comercial"] == sim[0]["cod"]].iloc[0]
            pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
            self.sim_cut = {"id": "sim_cut", "name": "SIMULACRO · " + name, "pts": pts, "source": "auto",
                            "note": "Tramo del tren de prueba (no real)", "created_ts": time.time(),
                            "expires_ts": None, "ref": "sim"}
        else:
            self.sim_cut = None
        return before != (self.sim_cut is not None)

    def _sync_auto_cuts(self, df, acc, now):
        """Cada posible accidente corta automáticamente su tramo; se reabre solo cuando deja de detectarse."""
        refs = {f"auto|{a['cod']}" for a in acc}
        if not self.db_ok:
            if not self.demo:
                return False
            before = len(self.cuts)  # demo: tramos automáticos solo en memoria
            have = {c.get("ref") for c in self.cuts}
            for a in acc:
                if f"auto|{a['cod']}" not in have and a["cod"] not in self.no_autocut:
                    row = df[df["cod_comercial"] == a["cod"]].iloc[0]
                    pts, name = segment_for_train(row, self.station_info, self.cfg["cut_half_km"] * 1000)
                    self.cuts.append({"id": f"demo{len(self.cuts) + 1}", "name": name, "pts": pts, "source": "auto",
                                      "note": "Demo: cierre automático", "created_ts": now, "expires_ts": None,
                                      "ref": f"auto|{a['cod']}"})
            self.cuts = [c for c in self.cuts if c.get("ref") in refs]
            return before != len(self.cuts) or bool(refs - have)
        changed = False
        for a in acc:
            if a["cod"] in self.no_autocut:
                continue
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
            self._learn_stations(tr.last_df)
            cfg_eff = dict(self.cfg, stations_known=bool(self.stations))
            df = apply_stop_rules(tr.last_df, cfg_eff, tr.brake_memory, tr.last_ts)
            an = analyze(df, cfg_eff, self.all_cuts(), self.dismissed)
            self.dismissed &= set(df.loc[df["is_stopped"] == True, "cod_comercial"])  # noqa: E712
            self.no_autocut &= {a["cod"] for a in an["acc"]}        # al terminar el accidente se "olvida" la reapertura
            real_acc = [a for a in an["acc"] if not str(a["cod"]).startswith("SIM-")]
            changed = self._sync_sim_cut(df, an["acc"])
            changed = self._sync_auto_cuts(df, real_acc, now) or changed
            if changed:
                an = analyze(df, cfg_eff, self.all_cuts(), self.dismissed)
            events = build_events(df, an["risk"], an["cut"], an["acc"], self.station_info, an["close"], an.get("acc_overflow", 0))
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
        if ev["kind"] in ("stopped", "accident") and not self.stations_base:
            return                       # sin estaciones fiables el aviso suena, pero NO ensucia la memoria de 30 días
        if self.db_ok and ev["kind"] in INCIDENT_KINDS and not _is_sim(ev):
            db_incident_open(ev["kind"], ev["key"].split("|", 1)[1], now, ev.get("lat"), ev.get("lon"),
                             ev["msg"], SEVERITY[ev["kind"]])

    def _on_cleared(self, kind, key, now):
        if self.db_ok and kind in INCIDENT_KINDS and "SIM-" not in key:
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
        self._flood_summary()

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
            e["mass"] = e["key"] in mass_keys
            self.events.append(e)
            if self.db_ok and not _is_sim(e):
                db_log(e)
            if e["key"] not in mass_keys and self._can_push(e):
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
            df = apply_stop_rules(tr.last_df, dict(self.cfg, stations_known=bool(self.stations)), tr.brake_memory, tr.last_ts)
            return {
                "df": df, "fetched_at": tr.last_ts, "last_poll": tr.last_poll_ts,
                "stale": self.consecutive_errors > 0, "frozen": tr.frozen, "frozen_for": tr.frozen_for(now),
                "fetch_count": tr.fetch_count, "duplicate_polls": tr.duplicate_polls, "seq": self.events_seq,
                "active": list(self.active), "last_error": self.last_error, "no_position": tr.no_position,
                "raw_count": tr.raw_count, "demo": self.demo, "sim": dict(self.sim, trail=list(self.sim["trail"])), "stations_source": self.stations_source,
                "learned": len(self.learned), "monitor_stopped": self.user_stopped, "push_on": self.push_enabled,
                "secondary": self.secondary, "primary_pid": self.primary_pid, "push_suppressed": self.push_suppressed, "routes": self.routes, "routes_dbg": self.routes_dbg,
                "routes_error": self.routes_error, "stations_error": self.stations_error, "newest_gps_age": tr.newest_gps_age,
                "thread_alive": bool(self.thread and self.thread.is_alive()),
                "db_ok": self.db_ok, "poll_s": self.poll_s,
                "incidents": [dict(i, fuente=i.get("fuente", "Adif")) for i in self.incidents] + list(self.alerts),
                "inc_ok": self.inc_ok, "alerts_error": self.alerts_error,
                "cerc": {"n": len(self.cerc_cache or []), "error": self.cerc_error, "trips_error": self.trips_error,
                         "delays": sum(1 for t in (self.cerc_cache or []) if t.get("_delay_known")),
                         "ok_ts": self.cerc_ok_ts},
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
A.freqs = {close:[900,1250], accident:[1000,1600], early:[600,600], brake:[700,950], stopped:[800,1000], risk:[950,1400], system:[500,500]};
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
        var n = new P.Notification(e.title, {body: e.body, tag: e.tag, requireInteraction: (e.rank >= 3)});
        n.onclick = function(){
          try { P.focus(); } catch(x) {}
          try { if (e.cod) P.history.replaceState(null, '', '?ver=' + encodeURIComponent(e.cod) + '&la=' + (e.lat == null ? '' : e.lat) + '&lo=' + (e.lon == null ? '' : e.lon)); } catch(x) {}
          try { n.close(); } catch(x) {}
        };
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
            "tag": ev.get("key", "renfe"), "speak": ev.get("speak") or ev["msg"],
            "cod": (ev.get("key", "").split("|") + [""])[1][:32], "lat": ev.get("lat"), "lon": ev.get("lon")}


def browser_sync(events, sound, siren_kind, siren_title, token):
    """Una sola llamada por ejecución: instala el puente, dispara eventos y sincroniza la sirena."""
    payload = {"sound": bool(sound), "events": [_event_payload(e) for e in events],
               "siren": ("hilo" if siren_kind == "risk" else "wail") if siren_kind else None,
               "sirenTitle": siren_title}
    data = (json.dumps(payload).replace("</", "<\\/").replace("<!--", "<\\!--")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
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
        cod = re.sub(r"<[^>]+>", "", str(tip)).split(" · ")[0].strip()
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
    return str(v or os.getenv("CARTO_API_KEY") or "TU_API_KEY_CARTO").strip()


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


PRESETS = {   # clave del deslizador -> valor
    "Estricto": {"p_early": 90, "p_minstop": 240, "p_radius": 1500, "p_acc": 900, "p_bms": 1.4, "p_bmin": 120,
                 "p_rttc": 90, "p_cttc": 90, "p_cclo": 40},
    "Normal": {"p_early": 45, "p_minstop": 120, "p_radius": 1200, "p_acc": 600, "p_bms": 1.0, "p_bmin": 100,
               "p_rttc": 120, "p_cttc": 120, "p_cclo": 30},
    "Sensible": {"p_early": 30, "p_minstop": 60, "p_radius": 1000, "p_acc": 240, "p_bms": 0.9, "p_bmin": 80,
                 "p_rttc": 120, "p_cttc": 150, "p_cclo": 25},
}


def cb_preset(name):
    for k, v in PRESETS[name].items():
        st.session_state[k] = v
    st.toast(f"Calibración «{name}» aplicada.", icon="🎚")


def cb_clear_incidents():
    db_clear_incidents()
    st.session_state.clr_ok = False
    st.toast("Historial de incidentes y eventos borrado.", icon="🧹")


def cb_close_card():
    st.session_state.sel_train = "—"


def sensitivity_tables(df, cfg):
    """Cuántos trenes se marcarían con otros valores (para calibrar sin adivinar)."""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    base = {**DEFAULT_CFG, **cfg}
    rt, rr = [], []
    for v in (30, 60, 90, 120, 180, 300):
        r = apply_stop_rules(df, dict(base, min_stop_s=v, early_stop_s=max(10, min(base["early_stop_s"], v - 10))), None, None)
        rt.append({"Detenido tras (s)": v, "Detenidos": int(r["is_stopped"].sum()), "Avisos tempranos": int(r["is_suspect"].sum())})
    for v in (500, 800, 1000, 1200, 1500, 2000, 3000):
        r = apply_stop_rules(df, dict(base, station_radius_m=v), None, None)
        rr.append({"Radio de estación (m)": v, "Detenidos": int(r["is_stopped"].sum())})
    return pd.DataFrame(rt), pd.DataFrame(rr)


def run_selftest(cfg):
    """Autodiagnóstico: escenarios sintéticos con TU calibración. No toca datos reales ni envía nada."""
    base = {**DEFAULT_CFG, **{k: v for k, v in cfg.items() if k in DEFAULT_CFG}}
    t0 = 1_900_000_000.0
    steps = int((max(base["min_stop_s"], base["accident_s"]) + 120) / 10) + 3

    def T(cod, lat, lon, t, **kw):
        d = {"codComercial": cod, "codProduct": 2, "latitud": lat, "longitud": lon, "ultRetraso": "0", "time": int(t)}
        d.update(kw)
        return d

    def run(make, stations=True):
        m = Monitor(demo=True)
        m.cfg.update(base)
        if stations:
            m.set_stations([{"code": "S1", "n": "Estación de prueba", "prov": "", "lat": 10.0, "lon": 10.0}])
        seen = set()
        for k in range(steps):
            t = t0 + 10 * k
            fill = [T(f"F{i}", 41 + i * 0.1 + 0.002 * k, i * 0.1, t) for i in range(12)]
            m.ingest({"trenes": fill + make(k, t)}, t)
            seen |= {e["key"] for e in m.active}
        m.pool.shutdown(wait=False)
        return seen

    res = []
    seen = run(lambda k, t: [T("P1", 38.0, -4.0, t, codEstAnt="A", codEstSig="B")])
    res.append(("Parado lejos de estación → DETENIDO", "stopped|P1" in seen, "stopped|P1"))
    seen = run(lambda k, t: [T("P2", 38.0, -4.0, t, codEstAnt="S1", codEstSig="S1")])
    res.append(("Parado «en estación» según el feed → SIN alarma", not any("P2" in x for x in seen), "sin avisos" if not any("P2" in x for x in seen) else str(seen)))
    seen = run(lambda k, t: [T("P3", 10.0, 10.0, t, codEstAnt="A", codEstSig="B")])
    res.append(("Parado junto a una estación conocida → SIN alarma", not any("P3" in x for x in seen), "sin avisos" if not any("P3" in x for x in seen) else str(seen)))
    seen = run(lambda k, t: [T("LEAD", 40.0 + (4000 + 92 * k) / 110540.0, -3.0, t), T("FOLL", 40.0 + 555 * k / 110540.0, -3.0, t)])
    res.append(("Tren a 200 km/h detrás de otro a 33 km/h → APROXIMACIÓN", any(x.startswith(("close|FOLL", "closecrit|FOLL")) for x in seen),
                [x for x in seen if "FOLL" in x]))
    seen = run(lambda k, t: [T("P5", 38.0, -4.0, t, codEstAnt="A", codEstSig="B")])
    res.append((f"Parado lejos más de {int(base['accident_s'])} s → POSIBLE ACCIDENTE", "accident|P5" in seen, "accident|P5"))
    seen = run(lambda k, t: [T(f"Q{i}", 38.0 + 0.3 * i, -4.0, t, codEstAnt="A", codEstSig="B") for i in range(5)])
    res.append(("5 trenes parados a la vez → NO se declaran accidentes (plausibilidad)",
                not any(x.startswith("accident|") for x in seen) and "sys|plaus" in seen, "descartados" if "sys|plaus" in seen else str(seen)))
    seen = run(lambda k, t: [T("C1-9", 38.5, -4.0, t, codProduct=200, _src="CERC", _status="STOPPED_AT", codEstAnt="X", codEstSig="X", _delay_known=False)])
    res.append(("Cercanías «parado en estación» → SIN alarma", not any("C1-9" in x for x in seen), "sin avisos" if not any("C1-9" in x for x in seen) else str(seen)))
    seen = run(lambda k, t: [T("P8", 38.0, -4.0, t, codEstAnt="A", codEstSig="B")], stations=False)
    res.append(("Sin estaciones: parado → suena, pero NO se declara accidente",
                "stopped|P8" in seen and "accident|P8" not in seen, sorted(x for x in seen if "P8" in x)))
    return res


def cb_focus(lat, lon, zoom=11):
    ss = st.session_state
    ss.focus = (float(lat), float(lon), int(zoom))
    ss.map_center, ss.map_zoom = [float(lat), float(lon)], int(zoom)
    ss.view_nonce = ss.get("view_nonce", 0) + 1


def cb_reset_view():
    ss = st.session_state
    ss.focus = None
    ss.map_center, ss.map_zoom = [40.0, -3.5], 6
    ss.view_nonce = ss.get("view_nonce", 0) + 1


def cb_zoom(delta):
    ss = st.session_state
    if ss.get("focus"):
        lat, lon, z = ss.focus
    else:
        (lat, lon), z = ss.get("map_center", [40.0, -3.5]), ss.get("map_zoom", 6)
    cb_focus(lat, lon, max(4, min(17, int(z) + int(delta))))


def cb_retry_stations():
    mon = _mon()
    mon.stations_try_ts = 0.0
    mon.poll_now()
    st.toast("Reintentando la descarga de estaciones…", icon="🏁")


def cb_view(cod, lat, lon):
    ss = st.session_state
    ss.sel_train = cod
    cb_focus(lat, lon, 11)


def cb_sim_create(lat, lon, heading, speed, delay):
    ss = st.session_state
    _mon().sim_set(active=True, lat=float(lat), lon=float(lon), heading=float(heading), speed=float(speed),
                   target=float(speed), delay=int(delay), decel=0.8, ts=time.time())
    ss.sim_target, ss.sim_heading, ss.sim_delay = int(speed), int(heading) % 360, int(delay)
    cb_focus(lat, lon, 11)
    st.toast("Tren de prueba creado: 🧪 SIM-001", icon="🧪")


def cb_sim_target():
    _mon().sim_set(target=float(st.session_state.sim_target), decel=0.8)


def cb_sim_heading():
    _mon().sim_set(heading=float(st.session_state.sim_heading))


def cb_sim_delay():
    _mon().sim_set(delay=int(st.session_state.sim_delay))


def cb_sim_stop(decel):
    st.session_state.sim_target = 0
    _mon().sim_set(target=0.0, decel=float(decel))


def cb_sim_halt():
    st.session_state.sim_target = 0
    _mon().sim_set(speed=0.0, target=0.0)


def cb_sim_delta(delta):
    ss = st.session_state
    v = max(0, min(350, int(ss.get("sim_target", 0)) + int(delta)))
    ss.sim_target = v
    _mon().sim_set(target=float(v), decel=0.8)


def cb_sim_remove():
    _mon().sim_remove()
    st.toast("Tren de prueba retirado.", icon="🧪")


def station_options(stations):
    """{etiqueta: (lat, lon)} para desplegables; evita nombres repetidos."""
    out = {}
    for s_ in stations:
        base = (s_.get("n") or s_.get("code") or "estación").strip() or "estación"
        label = base if base not in out else f"{base} · {s_['lat']:.3f},{s_['lon']:.3f}"
        out[label] = (s_["lat"], s_["lon"])
    return out


def add_sim_trail(m, trail):
    folium.PolyLine([list(p) for p in trail], color="#00e5ff", weight=4, opacity=0.9, dash_array="3 7",
                    tooltip="Recorrido del tren de prueba").add_to(m)


def add_sim_marker(m, row):
    kmh = float(row["speed_kmh"])
    pop = (f"<div style=\"font-family:Arial\"><b>🧪 SIMULACRO {esc(row['cod_comercial'])}</b><br>Tren de prueba (no real)<br>"
           f"Velocidad {kmh:.0f} km/h · rumbo {round(row['heading'])}°<br>Baja velocidad: {int(row['stopped_for_s'])} s</div>")
    folium.Marker(
        [row["lat"], row["lon"]], tooltip=f"🧪 SIMULACRO · {kmh:.0f} km/h", popup=folium.Popup(pop, max_width=260),
        icon=folium.DivIcon(icon_size=(0, 0), icon_anchor=(0, 0), html=(
            '<div style="position:absolute;left:-13px;top:-13px;width:26px;height:26px;background:#000;'
            'border:3px solid #00e5ff;transform:rotate(45deg);box-shadow:0 0 0 4px rgba(0,229,255,.45)"></div>'
            '<div style="position:absolute;left:20px;top:-12px;white-space:nowrap;background:#000;color:#00e5ff;'
            f'font:700 11px Arial;padding:2px 6px;border:1px solid #00e5ff">🧪 SIM · {kmh:.0f} km/h</div>'))).add_to(m)


def add_heat(m, df_f, modo, scores, stale_s):
    """Calor con círculos translúcidos que se acumulan (sin plugins: funciona en todos los modos de mapa)."""
    if modo == "Apagado" or df_f.empty:
        return
    age = pd.to_numeric(df_f["gps_age_s"], errors="coerce")
    d = df_f[~(age > stale_s) & ~df_f["cod_comercial"].astype(str).str.startswith("SIM-")]
    if modo == "Retrasos":
        w = (d["retraso_min"].clip(lower=0) / 30.0).clip(upper=1.0)
    elif modo == "Riesgo":
        w = d["cod_comercial"].map(lambda c: scores.get(c, {}).get("score", 0) / 100.0)
    else:
        w = pd.Series(0.35, index=d.index)
    for la, lo, x in zip(d["lat"], d["lon"], w):
        if x <= 0:
            continue
        col = "#2ecc71" if x < 0.34 else ("#f1c40f" if x < 0.67 else "#e74c3c")
        folium.Circle([float(la), float(lo)], radius=12000 + 18000 * float(x), stroke=False, fill=True,
                      fill_color=col, fill_opacity=0.10 + 0.12 * float(x)).add_to(m)


def cb_load_stations_now():
    """Descarga el CSV de estaciones de Renfe en el momento y deja el resultado (o el error exacto) en pantalla."""
    ss = st.session_state
    mon = _mon()
    try:
        est = mon._stations_csv()
        if est:
            mon.set_stations(est)
            save_stations_cache(est)
            with mon.lock:
                mon.stations_error, mon.stations_source = None, "Renfe (CSV)"
            ss.stations_msg = ("ok", f"✅ {len(est)} estaciones cargadas desde el CSV de Renfe (con "
                                     f"{sum(1 for x in est if x['prov'])} provincias y {sum(1 for x in est if x['code'])} códigos).")
        else:
            ss.stations_msg = ("err", "El CSV se descargó pero no encontré estaciones con coordenadas. "
                                      "Pulsa «🩺 Probar conexión» en SISTEMA para ver el inicio del archivo.")
    except Exception as e:  # noqa: BLE001 - el botón debe mostrar SIEMPRE la causa
        ss.stations_msg = ("err", f"❌ No se pudo descargar: {type(e).__name__}: {str(e)[:200]}")


def cb_monitor_stop():
    _mon().stop_user()
    st.toast("Monitor detenido: no se sondea ni se envía nada.", icon="⏻")


def cb_monitor_start():
    _mon().resume_user()
    st.toast("Monitor reanudado.", icon="▶")


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
    return int(hist_df.loc[m, "ref"].nunique())          # trenes DISTINTOS, no filas repetidas


def make_base_map(theme, center, zoom):
    """Un único mapa base fijo (sin selector interno): así no cambia de color al refrescar."""
    url, attr, bg = TILES.get(theme, TILES["Claro"])
    m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True, prefer_canvas=True)
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
                f'font:700 11px Arial;padding:2px 6px;border-radius:3px">TRAMO CORTADO · {esc(str(c["name"])[:42])}</div>'))
        ).add_to(m)


def add_history(m, hist_df):
    for r in hist_df.to_dict("records"):
        if pd.isna(r["lat"]) or pd.isna(r["lon"]):
            continue
        col = KIND_COLOR.get(r["kind"], "#888")
        folium.CircleMarker(
            [r["lat"], r["lon"]], radius=4 + 2 * int(r["severity"] or 1), color=col, weight=1, fill=True,
            fill_color=col, fill_opacity=0.35,
            tooltip=f"{LEVELS[r['kind']]['label']} · {esc(r['ref'])} · {fmt_clock(r['first_ts'], '%d/%m %H:%M')}").add_to(m)


def add_trains(m, df_f, info, sel_cod, acc_cods, scores, usar_cluster, stale_s=600):
    cluster = MarkerCluster(name=TRACK_TRAINS).add_to(m) if usar_cluster else None
    labels = 0
    for _, row in df_f.iterrows():
        cod = row["cod_comercial"]
        if str(cod).startswith("SIM-"):
            add_sim_marker(m, row)
            continue
        is_stopped, is_suspect, is_braking = bool(row["is_stopped"]), bool(row["is_suspect"]), bool(row["braking"])
        is_acc = cod in acc_cods
        stale = pd.notna(row["gps_age_s"]) and row["gps_age_s"] > stale_s
        color = "#8b949e" if stale else ("#ff0000" if is_acc else color_retraso(row["retraso_min"], is_stopped, is_suspect))
        cerc = str(row["src"]) == "CERC"
        if (not bool(row["delay_known"])) and not (stale or is_acc or is_stopped or is_suspect):
            color = "#5dade2"   # sin dato de retraso (Cercanías sin trip_updates)
        radius = 14 if is_acc else (12 if is_stopped else (9 if is_suspect else (4 if cerc else 6)))
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
        if cerc:   # popup compacto: hay cientos de trenes
            pop = (f"<b>{esc(cod)}</b> · {esc(row['tipo'])}<br>{estado} · {esc(where_text(row['est_ant'], row['est_sig'], info))}<br>"
                   + (f"Retraso: {fmt_delay(row['retraso_min'])}" if bool(row["delay_known"]) else "Retraso: sin dato")
                   + f"<br>Estado GTFS: {esc(row['status'])}")
        ruta_t = (f"{esc(label_est(row['origen'], info))} → {esc(label_est(row['destino'], info))}<br>"
                  if (row["origen"] or row["destino"]) else "")
        tip = (f"<b>{esc(cod)}</b> · {row['speed_kmh']:.0f} km/h<br>{esc(row['tipo'])} · {estado}<br>{ruta_t}"
               f"{esc(where_text(row['est_ant'], row['est_sig'], info))}<br>"
               + (f"Retraso: {fmt_delay(row['retraso_min'])}" if bool(row["delay_known"]) else "Retraso: sin dato")
               + (f"<br>Baja velocidad: {int(row['stopped_for_s'])} s" if row["stopped_for_s"] > 0 else "")
               + f"<br>Riesgo: {sc}/100")
        marker = folium.CircleMarker(
            location=[row["lat"], row["lon"]], radius=radius, color=color, fill=True, fill_color=color,
            fill_opacity=0.9, weight=2, popup=folium.Popup(pop, max_width=300),
            tooltip=folium.Tooltip(tip, sticky=True))
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

    # --- Acceso: si defines EBM_PASSWORD (variable de entorno o st.secrets) la interfaz exige contraseña ---
    pw = os.getenv("EBM_PASSWORD")
    if not pw:
        try:
            pw = st.secrets.get("EBM_PASSWORD")
        except Exception:  # noqa: BLE001
            pw = None
    if pw and not ss.get("auth_ok"):
        st.markdown("### 🔒 Emergency Brake Monitor")
        entered = st.text_input("Contraseña", type="password", key="auth_pw")
        if entered:
            if hmac.compare_digest(entered.encode("utf-8"), str(pw).encode("utf-8")):
                ss.auth_ok = True
                st.rerun()
            else:
                time.sleep(1.0)          # frena la fuerza bruta
                st.error("Contraseña incorrecta.")
        return

    try:                                   # clic en una notificación del navegador -> abre ese tren
        qp = st.query_params
        ver = qp.get("ver")
        if ver and re.fullmatch(r"[A-Za-z0-9._#:-]{1,32}", str(ver)):
            la_, lo_ = to_float(qp.get("la")), to_float(qp.get("lo"))
            ss.sel_train = str(ver)
            if la_ is not None and lo_ is not None and -90 <= la_ <= 90 and -180 <= lo_ <= 180:
                cb_focus(la_, lo_, 11)
            qp.clear()
    except Exception:  # noqa: BLE001 - versión sin st.query_params
        pass

    # --- Monitor y primer dato ---
    demo = bool(ss.get("demo_mode", False))
    mon = _mon()
    mon.ensure_running()
    if ss.get("mon_id") != id(mon):  # al cambiar real <-> demo se reinicia el seguimiento de eventos y la sirena
        ss.mon_id = id(mon)
        ss.pop("last_seq", None)
        ss.siren = None
        ss.siren_ver = ss.get("siren_ver", 0) + 1
    if not mon.stations_base:
        mon.set_stations(load_stations_cache())
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
        t_par, t_cal, t_cut, t_acc, t_tel, t_can, t_inc, t_reg, t_sis = st.tabs(
            ["⚙ PARÁMETROS", "🎚 CALIBRAR", "🚧 TRAMOS CORTADOS", "💥 ACCIDENTES (30 d)", "📊 TELEMETRÍA", "📡 CANALES",
             "🛰 INCIDENCIAS ADIF", "📜 REGISTRO", "🩺 SISTEMA"])

        with t_par:
            p1, p2, p3 = st.columns(3)
            with p1:
                early_stop_s = st.slider("Aviso temprano tras (s a baja velocidad)", 10, 180, DEFAULT_CFG["early_stop_s"], 5, key="p_early")
                min_stop_s = st.slider("Detenido confirmado tras (s)", 20, 300, DEFAULT_CFG["min_stop_s"], 10, key="p_minstop")
                station_radius_m = st.slider("Distancia mínima a estación (m)", 200, 3000, DEFAULT_CFG["station_radius_m"], 100, key="p_radius")
                if early_stop_s >= min_stop_s:
                    st.caption("⚠ El aviso temprano debe ser menor que el tiempo de detenido confirmado.")
                accident_s = st.slider("Posible accidente: detenido (s) lejos de estación", 60, 900, DEFAULT_CFG["accident_s"], 30, key="p_acc")
            with p2:
                risk_dist_m = st.slider("Distancia de riesgo (m)", 1000, 15000, DEFAULT_CFG["risk_dist_m"], 500)
                risk_ttc_s = st.slider("Tiempo hasta contacto máx. (s)", 30, 600, DEFAULT_CFG["risk_ttc_s"], 10, key="p_rttc")
                risk_heading_deg = st.slider("Tolerancia de rumbo (°)", 15, 90, DEFAULT_CFG["risk_heading_deg"], 5)
                risk_min_kmh = st.slider("Velocidad mínima en marcha (km/h)", 10, 200, DEFAULT_CFG["risk_min_kmh"], 5)
            with p3:
                brake_min_kmh = st.slider("Frenada brusca: velocidad previa mín. (km/h)", 40, 300, DEFAULT_CFG["brake_min_kmh"], 10, key="p_bmin")
                brake_ms2 = st.slider("Frenada brusca: deceleración (m/s²)", 0.4, 2.0, float(DEFAULT_CFG["brake_ms2"]), 0.1, key="p_bms")
                cut_half_km = st.slider("Tramo cortado automático: ± km alrededor del tren", 1, 50, DEFAULT_CFG["cut_half_km"], 1)
                cut_warn_m = st.slider("Aviso a trenes que se acercan a un tramo cortado (m)", 2000, 30000, DEFAULT_CFG["cut_warn_m"], 1000)
                risk_include_suspect = st.checkbox("Riesgo también contra trenes con aviso temprano",
                                                   value=DEFAULT_CFG["risk_include_suspect"])
            st.markdown("**⚡ Aproximación entre trenes** (avisa cuando un tren rápido alcanza a uno más lento que va delante)")
            ca, cb_, cc, cd = st.columns(4)
            close_on = ca.checkbox("Activar detección", value=True, key="close_on")
            close_gap_m = cb_.slider("Hueco máx. a vigilar (m)", 1000, 20000, DEFAULT_CFG["close_gap_m"], 500)
            close_ttc_s = cc.slider("Alcance en menos de (s)", 30, 600, DEFAULT_CFG["close_ttc_s"], 10, key="p_cttc")
            close_closing_kmh = cd.slider("Cierre mínimo (km/h)", 5, 100, DEFAULT_CFG["close_closing_kmh"], 5, key="p_cclo")
            ce, cf, cg = st.columns(3)
            close_decel = ce.slider("Frenado de servicio supuesto (m/s²)", 0.3, 1.2, float(DEFAULT_CFG["close_decel"]), 0.1)
            close_lateral_m = cf.slider("Desvío lateral máx. (m)", 50, 1000, DEFAULT_CFG["close_lateral_m"], 50)
            close_heading_deg = cg.slider("Tolerancia de rumbo entre trenes (°)", 10, 90, DEFAULT_CFG["close_heading_deg"], 5)
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
                   "cut_half_km": cut_half_km, "cut_warn_m": cut_warn_m, "close_on": close_on,
                   "close_gap_m": close_gap_m, "close_ttc_s": close_ttc_s, "close_closing_kmh": close_closing_kmh,
                   "close_decel": close_decel, "close_lateral_m": close_lateral_m, "close_heading_deg": close_heading_deg}

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
            push_label = st.selectbox("Enviar avisos desde el nivel", list(PUSH_LEVELS.keys()), index=2)
            cfg["push_min_rank"] = PUSH_LEVELS[push_label]
            push_on = st.checkbox("📤 Enviar avisos externos (Telegram / ntfy / webhook)", value=True, key="push_on")
            mon.set_push(push_on)
            pc1, pc2 = st.columns(2)
            pc1.button("⏻ Detener el monitor (corta también los envíos)", key="btn_mon_stop", on_click=cb_monitor_stop, **stretch)
            pc2.button("▶ Reanudar el monitor", key="btn_mon_start", on_click=cb_monitor_start, **stretch)
            st.caption("Cerrar la pestaña del navegador NO detiene el monitor: sigue en el servidor (por diseño, para vigilar "
                       "sin pantalla). Para pararlo del todo usa este botón o Ctrl+C en la terminal. Máximo 6 envíos cada 5 min.")
            for lbl, val, ok_ in (("Adif", adif_url, valid_http_url), ("Webhook", webhook, valid_http_url),
                                  ("Servidor ntfy", ntfy_server if ntfy_topic else "", valid_http_url),
                                  ("Topic de ntfy", ntfy_topic, valid_topic)):
                if val and not ok_(val):
                    st.warning(f"{lbl}: valor no válido (solo http/https; el topic solo admite letras, números, - y _). Se ignora.")
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
    full_cfg = {**DEFAULT_CFG, **cfg, "stations_known": bool(mon.stations_base)}
    try:
        an = analyze(df, full_cfg, snap["cuts"], snap["dismissed"])
    except Exception as e:  # noqa: BLE001 - un fallo de análisis no puede dejar el mapa vacío
        st.error(f"Fallo en el análisis de riesgo ({type(e).__name__}); se muestran los trenes sin indicadores.")
        an = {"risk": [], "acc": [], "cut": [], "close": [], "scores": {}}
    risk_alerts, cut_alerts, acc, scores = an["risk"], an["cut"], an["acc"], an["scores"]
    close_alerts = an.get("close", [])
    acc_cods = {a["cod"] for a in acc}
    hist_df = db_incidents(RETENTION_DAYS) if snap["db_ok"] else pd.DataFrame(columns=INC_COLUMNS)
    siren_rank = SIREN_LEVELS[ss.get("siren_label", list(SIREN_LEVELS.keys())[0])]
    sound_on = bool(ss.audio_ready and not ss.get("mute", False))
    now = time.time()

    # ================= PESTAÑAS INFERIORES: tramos, accidentes, telemetría, adif, registro, sistema =================
    with bottom:
        with t_cal:
            st.markdown("**🎚 Calibración**: elige la sensibilidad y comprueba qué se marcaría con tus datos de ahora")
            pc = st.columns(3)
            pc[0].button("🛡 Estricto (menos alertas)", key="pre_e", on_click=cb_preset, args=("Estricto",), **stretch)
            pc[1].button("⚖ Normal (recomendado)", key="pre_n", on_click=cb_preset, args=("Normal",), **stretch)
            pc[2].button("📡 Sensible (más alertas)", key="pre_s", on_click=cb_preset, args=("Sensible",), **stretch)
            st.caption("Los perfiles mueven los deslizadores de ⚙ PARÁMETROS (aviso temprano, detenido, radio de estación, "
                       "accidente, frenada y aproximación). Hoy hay temporal (DANA): con mal tiempo es normal que haya más "
                       "avisos REALES; usa Estricto si quieres solo los más claros.")
            age_ok = pd.to_numeric(df["gps_age_s"], errors="coerce") if not df.empty else pd.Series(dtype=float)
            cerc_df = df[df["src"] == "CERC"] if not df.empty else df
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Estaciones (descargadas + aprendidas)", f"{len(mon.stations_base)} + {snap['learned']}")
            h2.metric("Trenes con GPS fresco", f"{int((age_ok <= full_cfg['gps_stale_s']).sum())} / {len(df)}" if len(df) else "0")
            h3.metric("Cercanías con retraso conocido", f"{int(cerc_df['delay_known'].sum())} / {len(cerc_df)}" if len(cerc_df) else "—")
            h4.metric("Edad del feed", f"{int(now - (snap['source_ts'] or snap['fetched_at']))} s")
            ev1, ev24 = db_event_counts(1), db_event_counts(24)
            if not snap["db_ok"]:
                st.caption("Sin SQLite no hay estadística de alertas.")
            else:
                tabla = pd.DataFrame({"Última hora": ev1.groupby("nivel")["n"].sum(), "Últimas 24 h": ev24.groupby("nivel")["n"].sum()}).fillna(0).astype(int)
                st.markdown("**Alertas nuevas por tipo**")
                st.dataframe(tabla)
                if not ev24.empty:
                    top_ = ev24.assign(tren=ev24["clave"].str.split("|").str[1]).groupby("tren")["n"].sum().nlargest(8)
                    st.caption("Trenes que más alertas generan (si siempre son los mismos, sospecha de una estación que falta): "
                               + ", ".join(f"{k} ({v})" for k, v in top_.items()))
            t_s, t_r = sensitivity_tables(df, full_cfg)
            if not t_s.empty:
                x1, x2 = st.columns(2)
                x1.markdown("**¿Cuántos se marcarían según el tiempo?**")
                x1.dataframe(t_s, hide_index=True)
                x2.markdown("**¿Y según el radio de estación?**")
                x2.dataframe(t_r, hide_index=True)
            cand = df[(df["is_stopped"] == True) | (df["is_suspect"] == True)] if not df.empty else df  # noqa: E712
            st.markdown(f"**Trenes marcados ahora: {len(cand)}**")
            if len(cand):
                st.dataframe(cand[["cod_comercial", "tipo", "src", "status", "stopped_for_s", "dist_to_station", "gps_age_s", "est_ant", "est_sig"]]
                             .rename(columns={"cod_comercial": "Tren", "src": "Origen", "stopped_for_s": "Baja vel. (s)",
                                              "dist_to_station": "A estación (m)", "gps_age_s": "GPS (s)"}), hide_index=True)
                st.caption("Si ves trenes con «A estación» vacío o muy pequeño, o «en estación» en el feed, son falsos positivos probables.")
            st.markdown("**✅ Autodiagnóstico** (comprueba que cada regla funciona con TU calibración)")
            if st.button("▶ Ejecutar autodiagnóstico", key="btn_selftest", **stretch):
                ss.selftest = run_selftest(full_cfg)
            if ss.get("selftest"):
                st.dataframe(pd.DataFrame([{"Prueba": n, "Resultado": "✅ OK" if ok else "❌ FALLA", "Detalle": str(d)[:120]}
                                           for n, ok, d in ss.selftest]), hide_index=True)
                bad = sum(1 for _, ok, _ in ss.selftest if not ok)
                (st.error if bad else st.success)(f"{bad} prueba(s) fallan con esta calibración." if bad else "Todas las reglas responden como se espera.")

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
                est_opts = station_options(mon.stations)
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
            k1.metric("Posibles accidentes 24 h (trenes distintos)", a24)
            k2.metric("7 días", a7)
            k3.metric("30 días", a30)
            k4.metric("Detenciones 30 d", count_kind(hist_df, "stopped", 30 * 86400))
            k5.metric("Riesgos 30 d", count_kind(hist_df, "risk", 30 * 86400))
            with st.expander("🧹 Mantenimiento del historial"):
                st.checkbox("Confirmo que quiero borrar TODO el historial de incidentes y eventos", key="clr_ok")
                st.button("🧹 Borrar historial", key="btn_clr", on_click=cb_clear_incidents, disabled=not ss.get("clr_ok"))
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
            if snap["alerts_error"]:
                st.warning(f"Avisos oficiales de Renfe (GTFS-RT): no disponibles ({snap['alerts_error']}).")
            if snap["inc_cfg"] and snap["inc_ok"] is False:
                st.warning("Adif no responde; se reintenta cada 3 minutos.")
            if not snap["inc_cfg"]:
                st.caption("Fuente Adif opcional: indica una URL JSON en ADIF_INCIDENTS_URL o en CANALES "
                           "(campos titulo, texto, ambito y, si quieres dibujar el corte, 'tramo': [[lat,lon],[lat,lon]]).")
            niv = {"grave": 0, "leve": 1, "info": 2}
            if snap["incidents"]:
                from collections import Counter
                cnt = Counter(i.get("causa", "Motivo no comunicado") for i in snap["incidents"])
                st.caption("Causas (deducidas del texto del aviso): " + " · ".join(f"{k} {v}" for k, v in cnt.most_common()))
            for i in sorted(snap["incidents"], key=lambda x: niv.get(x["nivel"], 3)):
                st.markdown(f'<div class="inc {i["nivel"]}"><b>{esc(i["titulo"])}</b>{esc(i["texto"])}'
                            f'<br><small style="color:#7d8da0">{esc(i["ambito"])} · {esc(i.get("fuente", ""))} · causa: {esc(i.get("causa", "—"))}</small></div>',
                            unsafe_allow_html=True)
            if not snap["incidents"] and not snap["alerts_error"]:
                st.caption("No hay avisos oficiales activos en este momento.")

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
            _st = mon.stations
            if _st:
                st.markdown(f"**Estaciones (detalle):** con código {sum(1 for x in _st if x.get('code'))} · con nombre "
                            f"{sum(1 for x in _st if x.get('n'))} · con provincia {sum(1 for x in _st if x.get('prov'))} de {len(_st)} · "
                            f"ejemplo: {[(x.get('code'), x.get('n'), x.get('prov')) for x in _st[:3]]}")
            cc = snap["cerc"]
            st.markdown(f"**Red completa (Cercanías/Rodalies/Tram):** {cc['n']} trenes · con retraso conocido {cc['delays']}"
                        + (f" · último dato hace {int(time.time() - cc['ok_ts'])} s" if cc["ok_ts"] else "")
                        + (f" · problema posiciones: {cc['error']}" if cc["error"] else "")
                        + (f" · retrasos no disponibles ({cc['trips_error']})" if cc["trips_error"] else ""))
            dbg = snap["routes_dbg"]
            st.markdown(f"**Rutas y horarios:** {len(snap['routes'])} trenes con paradas"
                        + (f" · registros: {dbg['registros']} · campos del primer registro: {dbg['campos']}" if dbg else "")
                        + (f" · problema: {snap['routes_error']}" if snap["routes_error"] else ""))
            e1, e2 = st.columns([2, 1])
            with e1:
                st.markdown(f"**Estaciones:** {len(mon.stations)} cargadas (fuente: {snap['stations_source'] or 'ninguna'})"
                            + (f" · último problema: {snap['stations_error']}" if snap["stations_error"] else ""))
                up = st.file_uploader("Subir estaciones propias (GeoJSON, o CSV con lat, lon, codigo, nombre, provincia)",
                                      type=["geojson", "json", "csv"], key="up_est")
                if up is not None and up.size > 50 * 1024 * 1024:
                    st.error("Archivo demasiado grande (máx. 50 MB).")
                elif up is not None and ss.get("up_sig") != (up.name, up.size):
                    try:
                        text = decode_text(up.getvalue())
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
            st.button("📥 Descargar CSV de Renfe ahora", key="btn_dl_est", on_click=cb_load_stations_now, **stretch)
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
        for n_ev, e in enumerate(new_events):
            lvl = LEVELS[e["kind"]]
            # (sin toast: no se puede pulsar; las alertas son botones en la franja superior y en ALERTAS)
            if e.get("phase") == "nuevo" and lvl["rank"] >= siren_rank and lvl["rank"] > 0 and not e.get("mass"):
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
        if snap["secondary"]:
            env_txt, env_state = "COPIA 2ª", "caution"
        elif not canales:
            env_txt, env_state = "SIN CANAL", "caution"
        elif not snap["push_on"] or snap["monitor_stopped"]:
            env_txt, env_state = "PAUSADOS", "caution"
        else:
            env_txt, env_state = "ACTIVOS", "ok"
        st.markdown('<div class="ann-grid">' + "".join([
            ann("Accidente", len(acc), "warn" if acc else "ok"),
            ann("Aproximación", len(close_alerts), "warn" if close_alerts else "ok"),
            ann("Riesgo", n_risk, "warn" if n_risk else "ok"),
            ann("Detenidos", n_stop, "warn" if n_stop else "ok"),
            ann("Avisos", n_early, "caution" if n_early else "ok"),
            ann("Frenadas", n_brake, "caution" if n_brake else "ok"),
            ann("Tramos cortados", len(snap["cuts"]), "warn" if snap["cuts"] else "ok"),
            ann("Accid. 24 h", a24, "caution" if a24 else "ok"),
            ann("Estaciones", f"{len(mon.stations_base)} (+{snap['learned']})" if (mon.stations_base or snap["learned"]) else "SIN DATOS",
                "ok" if mon.stations_base else "warn"),
            ann("Feed de datos", feed_txt, feed_state),
            ann("Monitor", "ACTIVO" if snap["thread_alive"] else ("DETENIDO" if snap["monitor_stopped"] else "CAÍDO"),
                "ok" if snap["thread_alive"] else "warn"),
            ann("Canales", len(canales) if canales else "NINGUNO", "ok" if canales else "caution"),
            ann("Envíos", env_txt, env_state),
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
        if snap["secondary"]:
            st.warning(f"⚠ Hay OTRA copia del programa en marcha (PID {snap['primary_pid']}). Esta copia NO envía avisos externos "
                       "para no duplicarlos. Cierra las demás con «pkill -f streamlit» y arranca solo una.")
        if snap["monitor_stopped"]:
            st.warning("⏻ Has detenido el monitor: no se actualizan datos ni se envía nada. Reanúdalo en CANALES.")
        if snap["push_suppressed"]:
            st.caption(f"📤 {snap['push_suppressed']} aviso(s) no enviados por el límite anti-saturación.")
        if snap["stale"]:
            st.warning("⚠ Sin conexión con Renfe: se muestra la última lectura válida.")
        if snap["frozen"]:
            st.warning(f"🧊 El feed de Renfe no cambia desde hace {int(snap['frozen_for'])} s: "
                       "la detección está en pausa para evitar falsas alarmas.")
        if snap["fetch_count"] < 2:
            st.info("Primera lectura: velocidad, rumbo y detenciones se calculan desde la segunda actualización.")
        if ss.get("stations_msg"):
            (st.success if ss.stations_msg[0] == "ok" else st.error)(ss.stations_msg[1])
        if not mon.stations_base or "PARCIAL" in str(snap["stations_source"]):
            st.button("📥 DESCARGAR ESTACIONES AHORA (CSV oficial de Renfe)", key="btn_dl_est_top",
                      on_click=cb_load_stations_now, type="primary", **stretch)
        if not mon.stations_base:
            st.error(f"🏁 Sin estaciones cargadas ({snap['stations_error'] or 'descargando de Renfe y OpenStreetMap…'}). "
                     "Mientras tanto las alarmas de «detenido» saltan SIN descartar estaciones: un tren parado en una "
                     "estación también avisará (salvo los que el feed marca «en estación»; aprendidas del feed: "
                     f"{snap['learned']}). Puedes subir un archivo o reintentar en la pestaña SISTEMA.")
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
        crit = sorted([e for e in snap["active"] if LEVELS[e["kind"]]["rank"] >= 3], key=lambda e: -LEVELS[e["kind"]]["rank"])
        if siren or crit:
            lines = "".join(f"<div>{LEVELS[e['kind']]['icon']} {esc(e['msg'])}</div>" for e in crit[:6])
            if len(crit) > 6:
                lines += f"<div>… y {len(crit) - 6} aviso(s) más: míralos en la pestaña ALERTAS.</div>"
            if not lines and siren:
                lines = f"<div>{esc(siren['msg'])}</div>"
            head = siren["label"] if siren else LEVELS[crit[0]["kind"]]["label"]
            since = f" · lleva {mmss(time.time() - siren['since'])}" if siren else ""
            st.markdown(f'<div class="master"><h4>⚠ MASTER WARNING · {esc(head)}{since}</h4>{lines}</div>',
                        unsafe_allow_html=True)
            first = next((e for e in crit if e.get("lat") is not None), None)
            if first:
                cod_v = first["key"].split("|")[1]
                st.button(f"🎯 Ver tren {cod_v} en el mapa y en su ficha", key="btn_view", on_click=cb_view,
                          args=(cod_v, first["lat"], first["lon"]), **stretch)
        if siren:
            tag = "tono de dos notas" if siren["kind"] == "risk" else "barrido continuo"
            st.button(f"✔ RECONOCER Y SILENCIAR SIRENA  ({tag})", key="btn_ack", type="primary",
                      on_click=ack_siren, **stretch)
            if not sound_on:
                st.caption("🔕 La sirena está armada pero el sonido está desactivado o sin desbloquear en esta pestaña.")

    with alarm_zone:
        recent = [e for e in sorted(snap["active"], key=lambda e: (-LEVELS[e["kind"]]["rank"], e.get("first", 0)))
                  if LEVELS[e["kind"]]["rank"] >= 2 and e.get("lat") is not None and "|" in e["key"]][:6]
        if recent:
            st.caption("🔔 Alertas activas: pulsa una para ir al tren y ver su información (pasa el ratón para leerla)")
            cols_ = st.columns(len(recent))
            for i_, e_ in enumerate(recent):
                cod_ = e_["key"].split("|")[1]
                cols_[i_].button(f"{LEVELS[e_['kind']]['icon']} {cod_}", key=f"strip_{i_}", on_click=cb_view,
                                 args=(cod_, e_["lat"], e_["lon"]), help=e_["msg"][:400], **stretch)
        sel_ = ss.get("sel_train")
        if sel_ and sel_ != "—" and not df.empty:
            cur_ = df[df["cod_comercial"] == sel_]
            if not cur_.empty:
                t_ = cur_.iloc[0]
                sc_ = scores.get(sel_, {"score": 0, "why": []})
                rn_, _, rcol_ = risk_level(sc_["score"])
                est_ = "💥 Posible accidente" if sel_ in acc_cods else "🔴 Detenido en vía" if t_["is_stopped"] else \
                    ("🟠 Aviso temprano" if t_["is_suspect"] else "🟢 En marcha")
                ruta_ = (f"{esc(label_est(t_['origen'], info))} → {esc(label_est(t_['destino'], info))}"
                         if (t_["origen"] or t_["destino"]) else esc(t_["mat"] or ""))
                st.markdown(
                    f'<div class="ficha"><h3>🚆 {esc(sel_)} · {esc(t_["tipo"])}</h3><div class="r">{ruta_}</div><dl>'
                    f'<dt>Estado</dt><dd>{est_}</dd><dt>Velocidad</dt><dd>{t_["speed_kmh"]:.0f} km/h</dd>'
                    f'<dt>Retraso</dt><dd>{fmt_delay(t_["retraso_min"]) if bool(t_["delay_known"]) else "sin dato"}</dd>'
                    f'<dt>Dónde</dt><dd>{esc(where_text(t_["est_ant"], t_["est_sig"], info)) or "—"}</dd>'
                    + (f'<dt>Baja velocidad</dt><dd>{mmss(t_["stopped_for_s"])}</dd>' if t_["stopped_for_s"] > 0 else "")
                    + (f'<dt>A estación</dt><dd>{fmt_m(t_["dist_to_station"])} m</dd>' if t_["dist_to_station"] is not None else "")
                    + f'<dt>Riesgo</dt><dd style="color:{rcol_}">{sc_["score"]} · {rn_} {esc(" · ".join(sc_["why"]))}</dd></dl></div>',
                    unsafe_allow_html=True)
                qc1, qc2, qc3 = st.columns(3)
                qc1.button("🎯 Centrar mapa", key="card_center", on_click=cb_focus, args=(t_["lat"], t_["lon"], 12), **stretch)
                qc2.button("🚧 Cortar su tramo", key="card_cut", on_click=cb_cut_train, args=(sel_,), **stretch)
                qc3.button("✖ Cerrar ficha", key="card_close", on_click=cb_close_card, **stretch)

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
        m1, m2, m3, m4, m5, m6 = st.columns([1.3, 1.1, 1.2, 1.2, 1.4, 1.3])
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
                                        help="Solo para el modo clásico; el modo sin recarga ya recuerda el zoom.")
            st.checkbox("⚡ Mapa sin recarga", value=True, key="map_dynamic",
                        help="Actualiza los trenes SIN recargar el mapa: conserva zoom y posición, y los recuadros al pasar el ratón.")
            st.checkbox("⏸ Pausar mapa", key="map_pause", help="Congela el mapa para explorarlo sin que cambie nada.")

        with m6:
            calor = st.selectbox("Calor", ["Apagado", "Retrasos", "Densidad", "Riesgo"], index=1, key="calor",
                                 format_func=lambda x: f"🔥 {x}", label_visibility="collapsed",
                                 help="Mapa de calor: dónde se concentran los retrasos, los trenes o el riesgo.")

        df_f = df[df["grupo"].isin(list(grupos_sel) + ["Simulacro"])] if not df.empty else df
        if filtro_parados and not df_f.empty:
            df_f = df_f[(df_f["is_stopped"] == True) | (df_f["is_suspect"] == True)]  # noqa: E712

        total = len(df_f)
        ret_clip = df_f.loc[df_f["delay_known"], "retraso_min"].clip(lower=0) if total else pd.Series(dtype=float)
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
                        '<span style="--c:#ff2d2d">tramo cortado ▬ ▬</span><span style="--c:#5dade2">sin dato de retraso</span></div>', unsafe_allow_html=True)
            sim_s = snap["sim"]
            map_key_extra = ""
            follow = bool(sim_s["active"] and ss.get("sim_follow"))
            use_static = not map_engine.startswith("Interactivo")
            try:
                f_sig = inspect.signature(st_folium).parameters
            except (TypeError, ValueError):
                f_sig = {}
            dyn = (not use_static) and bool(ss.get("map_dynamic", True)) and "feature_group_to_add" in f_sig \
                and not ss.get("_dyn_failed")
            focus = ss.get("focus")
            if follow:
                center, zoom = [sim_s["lat"], sim_s["lon"]], 12
                map_key_extra = f"f{int(sim_s['lat'] * 1e4)}"
            elif focus:
                center, zoom = [focus[0], focus[1]], focus[2]
                if dyn:                       # en modo sin recarga la vista la guarda el propio mapa
                    ss.map_center, ss.map_zoom, ss.focus = list(center), zoom, None
            elif dyn or remember_view:
                center, zoom = ss.get("map_center", [40.0, -3.5]), ss.get("map_zoom", 6)
            else:
                center, zoom = [40.0, -3.5], 6

            def est_group():
                if not (ver_estaciones and mon.has_stations()):
                    return None
                fg_e = folium.FeatureGroup(name="Estaciones", show=True)
                for s_ in mon.stations:
                    folium.CircleMarker([s_["lat"], s_["lon"]], radius=4, color="#1f5fa8", fill=True, fill_color="#3b8eea",
                                        fill_opacity=0.85, weight=1,
                                        tooltip=esc(s_["n"] or s_["code"] or "estación")).add_to(fg_e)
                return fg_e

            def draw(target):
                for fn, args in ((add_history, (target, hist_df)), (add_cuts, (target, snap["cuts"]))):
                    if (fn is add_history and not (ver_hist and not hist_df.empty)) or (fn is add_cuts and not ver_tramos):
                        continue
                    try:
                        fn(*args)
                    except Exception as e:  # noqa: BLE001 - las capas extra nunca bloquean los trenes
                        st.caption(f"⚠ Capa omitida ({type(e).__name__}).")
                try:
                    add_heat(target, df_f, calor, scores, full_cfg["gps_stale_s"])
                except Exception as e:  # noqa: BLE001
                    st.caption(f"⚠ Capa de calor omitida ({type(e).__name__}).")
                if sim_s["active"] and len(sim_s["trail"]) > 1:
                    add_sim_trail(target, sim_s["trail"])
                add_trains(target, df_f, info, ss.get("sel_train"), acc_cods, scores, usar_cluster, full_cfg["gps_stale_s"])

            groups = None
            if dyn and ss.get("map_pause") and ss.get("_map_obj") is not None:
                m, groups = ss._map_obj                       # mapa congelado: se reutiliza tal cual
                st.caption("⏸ Mapa en pausa: no se actualiza hasta que lo reactives.")
            else:
                m = make_base_map(theme, center, zoom)
                if dyn:
                    fg_main = folium.FeatureGroup(name="Datos", show=True)
                    draw(fg_main)
                    groups = [fg_main]
                    ek = (len(mon.stations), bool(ver_estaciones))
                    cache = ss.get("_est_cache")
                    fg_e = cache[1] if (cache and cache[0] == ek) else est_group()
                    ss._est_cache = (ek, fg_e)
                    if fg_e is not None:
                        groups.append(fg_e)
                    ss._map_obj = (m, groups)
                else:
                    fg_e = est_group()
                    if fg_e is not None:
                        fg_e.add_to(m)
                    draw(m)
                st.caption(f"🚆 {len(df_f)} trenes dibujados de {len(df)} con posición · 🏁 {len(mon.stations)} estaciones cargadas"
                           f"{'' if ver_estaciones else ' (ocultas)'} · tema: {theme} · {'⚡ sin recarga' if dyn else 'modo clásico'}")

            map_data = None
            if not use_static:
                returned = ["last_object_clicked", "last_object_clicked_tooltip"]
                if dyn or remember_view:
                    returned += ["center", "zoom"]
                skey = f"mapa_{theme}_{ss.view_nonce}{map_key_extra}"
                try:
                    if dyn:
                        kw = {"feature_group_to_add": groups}
                        if "center" in f_sig and "zoom" in f_sig:
                            kw.update(center=center, zoom=zoom)
                        map_data = st_folium(m, key=skey, use_container_width=True, height=620, returned_objects=returned, **kw)
                    else:
                        map_data = st_folium(m, key=skey, use_container_width=True, height=620, returned_objects=returned)
                except TypeError:
                    if dyn:                       # versión sin soporte para actualizar capas: vuelve al modo clásico
                        ss._dyn_failed = True
                        st.rerun()
                    use_static = True
                except Exception as e:  # noqa: BLE001 - el mapa nunca debe tumbar la herramienta
                    if dyn:
                        ss._dyn_failed = True        # primero se reintenta en modo clásico
                        st.rerun()
                    st.error(f"El mapa interactivo falló ({type(e).__name__}); se muestra el mapa estático.")
                    use_static = True
            if use_static:
                st.caption("🗺 Mapa estático: se dibuja siempre, pero sin clic en trenes (usa el popup de cada punto).")
                render_html(m.get_root().render(), height=640)
            if map_data and (dyn or remember_view):
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
            tab_arr, tab_al, tab_rk, tab_tren, tab_list, tab_sim = st.tabs(["⏱ RETRASOS", "🚨 ALERTAS", "🎚 RIESGO", "🚆 TREN", "📋 TRENES", "🧪 SIM"])

            with tab_al:
                active = sorted(snap["active"], key=lambda e: -LEVELS[e["kind"]]["rank"])
                if not active:
                    st.markdown('<div class="eicas"><div class="nominal">● SISTEMA NOMINAL — sin trenes detenidos '
                                'lejos de estaciones.</div></div>', unsafe_allow_html=True)
                else:
                    st.caption("Pulsa «🎯 Ver» para centrar el mapa y abrir la ficha del tren (arriba, sobre el mapa).")
                    for i_a, e in enumerate(active[:12]):
                        cls = "risk" if e["kind"] == "accident" else e["kind"]
                        st.markdown(
                            f'<div class="eicas"><div class="msg {cls}"><b>{LEVELS[e["kind"]]["icon"]} {LEVELS[e["kind"]]["label"]}'
                            f' · {mmss(time.time() - e.get("first", time.time()))}</b>{esc(e["msg"])}</div></div>', unsafe_allow_html=True)
                        if e.get("lat") is not None and "|" in e["key"]:
                            st.button("🎯 Ver", key=f"alv_{i_a}", on_click=cb_view, args=(e["key"].split("|")[1], e["lat"], e["lon"]))
                    if len(active) > 12:
                        st.caption(f"… y {len(active) - 12} más")

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
                    ret = ret[ret.apply(lambda r: train_in_zone(zona, r, info), axis=1)].sort_values("retraso_min", ascending=False)
                if len(ret):
                    st.caption(f"{len(ret)} tren(es) con {min_ret} min de retraso o más · derecha: llegada al destino "
                           "(tachada = prevista, debajo = estimada)" if snap["routes"] else
                           f"{len(ret)} tren(es) con {min_ret} min de retraso o más · sin horarios de destino: "
                           "se muestra la próxima parada")
                elif n_zona_antes:
                    st.caption("Ninguno en esta zona ahora mismo. (Si no se conoce el destino, se usa la posición actual del tren.)")
                else:
                    st.caption(f"Ningún tren de los elegidos tiene {min_ret} min de retraso o más.")
                ver_todos = st.checkbox("Ver todos", key="arr_all") if len(ret) > 12 else False
                rows_html = ""
                for _, t in (ret if ver_todos else ret.head(12)).iterrows():
                    nv = "grave" if t["retraso_min"] >= 15 else "leve"
                    where = esc(where_text(t["est_ant"], t["est_sig"], info)) or "—"
                    ruta = (f'{esc(label_est(t["origen"], info))} → {esc(label_est(t["destino"], info))}'
                            if (t["origen"] or t["destino"]) else esc(t["mat"] or t["cod_comercial"]))
                    plan = planned_arrival(snap["routes"], t["cod_comercial"], t["destino"])
                    hs = (f"<del>{plan}</del>{add_minutes_hhmm(plan, max(0, int(t['retraso_min'])))}" if plan else
                          (f"{esc(label_est(t['est_sig'], info))}<br>{esc(t['hora_sig'])}" if t["hora_sig"] else ""))
                    rows_html += (
                        f'<div class="arr {nv}"><div class="min">+{int(t["retraso_min"])}</div>'
                        f'<div><div class="t">{esc(t["tipo"])} {ruta}<small>{esc(t["cod_comercial"])}</small></div>'
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
                    where = esc(where_text(t["est_ant"], t["est_sig"], info)) or "—"
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
                        + (f'<dt>Fuente</dt><dd>{"Cercanías (GTFS-RT)" if t["src"] == "CERC" else "Larga distancia"}'
                           f' {esc(t["status"])}</dd>')
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

    with col_panel:
        with tab_sim:
            sim = snap["sim"]
            st.caption("Tren virtual 🧪 SIM-001 (rombo negro con borde cian). Pasa por las mismas reglas que los trenes "
                       "reales, pero sus avisos NO se envían a Telegram/ntfy ni se guardan en la memoria de 30 días.")
            if not sim["active"]:
                preset = st.radio("Dónde colocarlo", ["Vía lejos de estaciones", "En una estación",
                                                      "Detrás del tren seleccionado", "Coordenadas"], key="sim_preset")
                lat0, lon0, hdg0, ok_place = DEMO_SPOT[0], DEMO_SPOT[1], 0, True
                if preset == "En una estación":
                    opts = station_options(mon.stations)
                    if opts:
                        k_ = st.selectbox("Estación", sorted(opts), key="sim_station")
                        lat0, lon0 = opts[k_]
                    else:
                        st.caption("No hay estaciones cargadas todavía.")
                        ok_place = False
                elif preset == "Detrás del tren seleccionado":
                    sel_ = ss.get("sel_train", "—")
                    cur_ = df[df["cod_comercial"] == sel_] if (sel_ != "—" and not df.empty) else df.iloc[0:0]
                    if cur_.empty or not bool(cur_.iloc[0]["has_heading"]):
                        st.caption("Primero selecciona un tren EN MARCHA (clic en el mapa o pestaña TREN).")
                        ok_place = False
                    else:
                        t_ = cur_.iloc[0]
                        gap_km = st.slider("Distancia detrás (km)", 1, 15, 6, key="sim_gap")
                        lat0, lon0 = offset_point(t_["lat"], t_["lon"], t_["heading"] + 180, gap_km * 1000)
                        hdg0 = float(t_["heading"])
                        st.caption(f"Se coloca detrás del tren {t_['cod_comercial']} ({t_['speed_kmh']:.0f} km/h), mismo rumbo.")
                elif preset == "Coordenadas":
                    lat0 = st.number_input("Latitud", value=40.0, format="%.5f", key="sim_lat")
                    lon0 = st.number_input("Longitud", value=-3.5, format="%.5f", key="sim_lon")
                if preset != "Detrás del tren seleccionado":
                    hdg0 = st.slider("Rumbo (° · 0 norte, 90 este)", 0, 359, 0, 5, key="sim_hdg0")
                v0 = st.slider("Velocidad inicial (km/h)", 0, 350, 120, 5, key="sim_v0")
                d0 = st.slider("Retraso (min)", -5, 120, 0, 1, key="sim_d0")
                st.button("➕ Crear tren de prueba", key="sim_create", on_click=cb_sim_create,
                          args=(lat0, lon0, hdg0, v0, d0), disabled=not ok_place, **stretch)
            else:
                st.slider("Velocidad objetivo (km/h)", 0, 350, int(ss.get("sim_target", sim["target"])), 5,
                          key="sim_target", on_change=cb_sim_target)
                st.slider("Rumbo (°)", 0, 359, int(ss.get("sim_heading", sim["heading"])), 5,
                          key="sim_heading", on_change=cb_sim_heading)
                st.slider("Retraso (min)", -5, 120, int(ss.get("sim_delay", sim["delay"])), 1,
                          key="sim_delay", on_change=cb_sim_delay)
                x1, x2 = st.columns(2)
                x1.button("▶ Arrancar", key="sim_go", on_click=cb_sim_target, **stretch)
                x2.button("⏸ Parar suave", key="sim_soft", on_click=cb_sim_stop, args=(0.8,), **stretch)
                x3, x4 = st.columns(2)
                x3.button("🛑 Frenada brusca", key="sim_hard", on_click=cb_sim_stop, args=(2.4,), **stretch)
                x4.button("⛔ Parar ya", key="sim_halt", on_click=cb_sim_halt, **stretch)
                x5, x6 = st.columns(2)
                x5.button("⏩ +20 km/h", key="sim_up", on_click=cb_sim_delta, args=(20,), **stretch)
                x6.button("⏪ −20 km/h", key="sim_dn", on_click=cb_sim_delta, args=(-20,), **stretch)
                st.checkbox("🎯 Seguir al tren de prueba en el mapa", key="sim_follow",
                            help="Centra el mapa en el tren en cada actualización (se mueve ~300-500 m por actualización a 120 km/h).")
                st.button("❌ Quitar tren de prueba", key="sim_rm", on_click=cb_sim_remove, **stretch)
                row_ = df[df["cod_comercial"] == SIM_ID] if not df.empty else df
                st.markdown(f"**Ahora:** {sim['speed']:.0f} km/h (objetivo {sim['target']:.0f}) · rumbo {sim['heading']:.0f}° · "
                            f"{sim['lat']:.4f}, {sim['lon']:.4f}")
                if not row_.empty:
                    r_ = row_.iloc[0]
                    sc_ = scores.get(SIM_ID, {"score": 0, "why": []})
                    st.caption(f"Medido por el monitor: {r_['speed_kmh']:.0f} km/h · baja velocidad {mmss(r_['stopped_for_s'])} · "
                               f"estación a {fmt_m(r_['dist_to_station'])} m · riesgo {sc_['score']} ({', '.join(sc_['why']) or '—'})")
                evs_ = [e for e in snap["active"] if "SIM-" in e["key"] or e["key"].endswith("|sim_cut")]
                if evs_:
                    for e_ in evs_:
                        st.warning(f"{LEVELS[e_['kind']]['icon']} {e_['msg']}")
                else:
                    st.caption("Sin alertas para el tren de prueba. (Parado dentro de una estación NO debe alarmar; "
                               "«detenido» necesita estar parado el tiempo configurado en PARÁMETROS.)")

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
