
# Emergency Brake Monitor A.M-D.C

> **Prototipo experimental.** Herramienta de observación y alerta temprana para el seguimiento de trenes en tiempo real. Publicada como código abierto para que la comunidad pueda revisarla, mejorarla y utilizarla.

**Nombre en memoria de Antonio Acedo Meneses y Daniel Cabañas Cob.**

---

## ⚠️ Aviso importante (leer antes de nada)

- **Esto NO es un sistema de seguridad ferroviaria.** No sustituye ni complementa a ASFA, ERTMS, LZB, ni a los centros de regulación de Adif o Renfe.
- Es un **prototipo de observación y análisis** basado en datos públicos. Los avisos que genera (proximidad, detenciones, frenadas) son **heurísticos** y pueden producir **falsos positivos y falsos negativos**.
- Los datos de posición pueden tener retrasos, errores o desaparecer sin aviso (el endpoint no es oficial).
- **No tomes ninguna decisión operativa, de seguridad o de gestión ferroviaria basándote en esta herramienta.**
- Si detectas un problema real en la red, contacta con Adif o Renfe a través de sus canales oficiales.

---

## Qué hace

`Emergency Brake Monitor A.M-D.C` es un panel de monitorización en tiempo real construido en Python + Streamlit. Consume datos públicos de posición de trenes de Renfe (endpoint del visor de larga distancia) y aplica lógica de seguimiento para detectar:

- **Trenes detenidos en vía** (parados lejos de estaciones durante un tiempo configurable).
- **Avisos tempranos** (baja velocidad sostenida lejos de estación, antes de confirmar detención).
- **Frenadas bruscas** (deceleración anómala a alta velocidad, lejos de estaciones).
- **Riesgo de alcance** (un tren en marcha acercándose a otro detenido, con rumbo compatible).
- **Retrasos** por tipo de servicio, zona geográfica y tren individual.

Y ofrece:

- Mapa interactivo (Folium) con trenes coloreados por estado y severidad.
- Panel lateral con alertas activas, llegadas con retraso y ficha por tren.
- **Sirena continua** en el navegador (dos tonos) que solo se detiene con el botón *RECONOCER*.
- Notificaciones del navegador, voz (SpeechSynthesis) y vibración en móvil.
- Envío opcional a **Telegram**, **ntfy** y **webhook** genérico.
- Registro persistente en **SQLite** de todos los eventos detectados.
- Monitor en segundo plano que funciona incluso sin pestañas abiertas.

---

## Estado del proyecto

**Experimental.** Es un prototipo. Está pensado como base abierta para que otros:

- Revisen la lógica de detección y la mejoren.
- Añadan fuentes de datos (Cercanías GTFS‑RT, incidencias Adif en otros formatos, AIS, etc.).
- Integren sistemas de notificación alternativos.
- Adapten la interfaz a otros operadores o redes.

Las contribuciones son bienvenidas. Se aceptan issues, pull requests y discusiones.

---

## Requisitos

- Python 3.10 o superior.
- Dependencias:

```bash
pip install streamlit streamlit-folium streamlit-autorefresh folium pandas numpy requests
```

---

## Ejecución

```bash
streamlit run emergency_brake_monitor.py
```

Se abrirá en `http://localhost:8501`.

> **Recomendación:** en producción, escúchalo solo en `127.0.0.1` y ponlo detrás de un proxy con TLS y autenticación (Caddy, Nginx, oauth2-proxy) si necesitas acceso remoto.

---

## Configuración opcional

Las credenciales de notificación pueden definirse con variables de entorno o con `st.secrets`. Los campos de la interfaz viven solo en memoria de la sesión.

| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram. |
| `TELEGRAM_CHAT_ID` | Chat o canal donde enviar los avisos. |
| `NTFY_TOPIC` | Topic de ntfy. |
| `NTFY_SERVER` | Servidor ntfy (por defecto `https://ntfy.sh`). |
| `ALERT_WEBHOOK_URL` | URL que recibirá un POST JSON por cada aviso. |
| `ADIF_INCIDENTS_URL` | URL JSON (si existe) con avisos de Adif. Formato flexible. |
| `RENFE_DB` | Ruta al archivo SQLite (por defecto `renfe_alertas.db`). |

---

## Estructura del código

- `Monitor`: hilo global que sondea Renfe, evalúa reglas y despacha notificaciones.
- `TrainTracker`: lógica pura (sin Streamlit) que calcula velocidad, rumbo y tiempos a baja velocidad por tren. Protege contra lecturas duplicadas, feed congelado, saltos de GPS y huecos largos.
- `apply_stop_rules` / `check_proximity_risk`: reglas de detección.
- `BRIDGE_JS`: puente de audio en el navegador (pitidos, sirena continua, voz, notificaciones).
- `db_*`: persistencia SQLite de eventos.
- Sección UI: cabecera tipo cabina, anunciadores, master warning, mapa y paneles.

---

## Limitaciones conocidas

- No hay acceso al grafo de vías. La detección de riesgo usa rumbo + distancia, no pertenencia a la misma vía: **en corredores con vías paralelas puede generar falsos positivos**.
- El endpoint de Renfe no es oficial ni documentado; puede cambiar o desaparecer.
- La resolución temporal de los datos es de ~15–30 s, insuficiente para seguridad real.
- `ADIF_INCIDENTS_URL` no tiene un endpoint público oficial; se deja preparado para cualquier feed JSON futuro.

---

## Licencia

---

## Dedicatoria

Este proyecto lleva las iniciales de **Antonio Acedo Meneses** y **Daniel Cabañas Cob**, maquinistas fallecidos en el accidente ferroviario de Urda (Toledo) el 28 de octubre de 2026.

La idea de esta herramienta no es sustituir a los sistemas de seguridad, sino recordar que detrás de cada punto en un mapa hay personas, y que cualquier mejora en la observación de la red puede ayudar a que no vuelva a ocurrir.

---

## Contribuir

1. Abre un issue describiendo qué quieres mejorar.
2. Haz un fork y una rama con un nombre descriptivo.
3. Envía un pull request con contexto y, si es posible, pruebas.

Se agradece especialmente:

- Revisión de la lógica de alertas.
- Añadido de fuentes de datos.
- Mejoras de accesibilidad (lectores de pantalla, teclado, contraste).
- Traducciones.

---

**Emergency Brake Monitor A.M-D.C** — prototipo experimental, código abierto, en memoria de quienes no pudieron frenar a tiempo y todas las victimas!
```

**Paro aquí.** Dime "go" y qué licencia quieres (MIT, Apache 2.0, GPL-3.0…) y te paso el `LICENSE`.
