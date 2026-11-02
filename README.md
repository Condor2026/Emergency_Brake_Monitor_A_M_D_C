# 🚆 Emergency Brake Monitor (A.M.D.C.)
![TheCondor](EmergencyBrakeMonitorCondor.jpg)

> **Prototipo experimental.** Herramienta de observación y alerta temprana para el seguimiento de trenes en tiempo real. Publicada como código abierto para que la comunidad pueda revisarla, mejorarla y utilizarla.

---

## ⚠️ Aviso importante (leer antes de nada)

- **Esto NO es un sistema de seguridad ferroviaria.** No sustituye ni complementa a ASFA, ERTMS, LZB, ni a los centros de regulación de Adif o Renfe.
- Es un **prototipo de observación y análisis** basado en datos públicos. Los avisos que genera (proximidad, detenciones, frenadas) son **heurísticos** y pueden producir **falsos positivos y falsos negativos**.
- Los datos de posición pueden tener retrasos, errores o desaparecer sin aviso (el endpoint no es oficial).
- **No tomes ninguna decisión operativa, de seguridad o de gestión ferroviaria basándote en esta herramienta.**
- Si detectas un problema real en la red, contacta con Adif o Renfe a través de sus canales oficiales.
- **El sistema de notificaciones (Telegram, ntfy, webhook) está implementado en el código, pero NO ha sido probado en un entorno real por el autor.** La lógica de envío existe, pero no se ha validado con credenciales reales ni con servidores en producción. Si decides usarlo, hazlo bajo tu propia responsabilidad y prueba primero con un mensaje de test (el código incluye un botón de "Enviar mensaje de prueba").

> **"En memoria de las víctimas y de los maquinistas que, como última opción, accionaron el freno."**

## 📖 La historia detrás del proyecto

Hace pocos días, un civil desarrolló una aplicación para avisar de los retrasos de Renfe. Le llovieron las críticas. Se le acusó de falta de innovación, de que era un "prototipo básico" y de que no aportaba nada nuevo. El chico se defendió: *"Si yo pude, ¿por qué no lo hizo Renfe?"*. Pero la presión y el acoso pudieron con él; se cansó y desapareció. La app ya no existe, sus cuentas? Eliminadas. 

Mientras todo eso pasaba, yo estaba construyendo otra cosa. Mientras otros se limitaban a criticar al chico y a decir que su idea no era innovadora, yo, que programo, pensaba en cómo mejorarla. Tenía ideas. Y me cabreé.

Así nació **Emergency Brake Monitor**, un sistema que lleva las siglas **A.M.D.C.** en su nombre. No son siglas técnicas. Son las iniciales de **los maquinistas** que, en los accidentes ferroviarios de este país, **accionaron la palanca del freno como última opción**. Es un homenaje a ellos y a las víctimas. Y es, sobre todo, una promesa: **que otros no pasen por lo mismo**.

![TheCondor](PANELCENTRAL.png) 

## 🛠️ ¿Qué es y para qué sirve?

**Emergency Brake Monitor** no es una app de retrasos. Es un sistema de **alerta temprana y monitorización de seguridad ferroviaria** que utiliza datos públicos de posición de trenes (Renfe/Adif) para detectar situaciones de peligro en tiempo real.

Su objetivo principal es **prevenir alcances y accidentes** cuando un tren se detiene en vía (por avería, incidente o cualquier motivo) y otro tren se aproxima por detrás. La aplicación genera una **alerta crítica sonora y visual** (similar a la alarma de un avión cuando detecta una colisión inminente) que no se detiene hasta que el operador la reconoce y toma acción.

**La app sirve para que otros no pasen por lo mismo y lleguen a frenar a tiempo cuando se para un tren delante, como en España.** Para que la alarma suene antes de que la única opción sea accionar el freno a mano.

## ⚙️ ¿Cómo funciona? (Explicación técnica y detallada)

El sistema se compone de varios módulos que trabajan en conjunto:

1. **Monitor en segundo plano (Hilo independiente):**
   - Un hilo de ejecución (independiente de la interfaz) sondea constantemente el feed público de Renfe (`flotaLD.json`) cada pocos segundos.
   - Almacena el estado de cada tren: posición, velocidad, rumbo, retraso, etc.
   - **Detecta anomalías:** Si un tren reduce su velocidad por debajo de 5 km/h y se mantiene así durante un tiempo configurable (por defecto 30-60 segundos) **lejos de una estación** (a más de 1 km), el sistema lo marca como "posible detenido en vía".

2. **Cálculo de riesgo de alcance:**
   - Si hay un tren detenido (o sospechoso de estarlo) y otro tren en movimiento se aproxima por la misma vía (mismo rumbo) y a una distancia y velocidad que implican un tiempo hasta el contacto (TTC) menor al umbral configurado (por defecto 120 segundos), se dispara una **alerta de riesgo crítico**.

3. **Detección de frenadas bruscas:**
   - El sistema calcula la deceleración de cada tren (m/s²) comparando lecturas consecutivas. Si un tren frena bruscamente (deceleración > 0.9 m/s²) lejos de una estación, se genera una alerta.

4. **Tramos cortados automáticos:**
   - Cuando se detecta un posible accidente, el sistema **cierra automáticamente un tramo** de vía (una polilínea aproximada alrededor del tren) y avisa a cualquier tren que se dirija hacia ese tramo.

5. **Memoria persistente (SQLite):**
   - Todos los incidentes (detenciones, frenadas, riesgos, accidentes) se guardan en una base de datos local durante **30 días**.
   - Esto permite analizar patrones, descargar historiales en CSV y tener un registro de lo ocurrido incluso si se cierra la aplicación.

6. **Canales de aviso:**
   - La alerta se muestra en la interfaz (interfaz tipo "cabina" con anunciadores y master warning).
   - Se activa una **sirena continua** en el navegador (con dos tonos distintos según la gravedad) que solo se detiene al pulsar "RECONOCER".
   - Se envían notificaciones push a **Telegram, ntfy y webhooks** (configurables).
   - Se puede activar una sirena de respaldo (reproductor nativo) si el navegador bloquea el audio.

7. **Probar y validar los canales de notificación:** El código de Telegram, ntfy y webhooks está listo, pero falta probarlo con credenciales reales. 
  *Interfaz de usuario (Streamlit):**
   - Mapa interactivo (Folium) con todos los trenes, colores según estado (normal, detenido, frenada, riesgo, accidente).
   - Paneles de telemetría (velocidad media, retrasos, series temporales).
   - Ficha detallada de cada tren.
   - Pestañas de configuración, tramos cortados, historial de accidentes, registro de eventos, etc.
8. El código de Telegram, ntfy y webhooks está listo, pero falta probarlo con credenciales reales. 


## 🚀 ¿En qué se diferencia de otras herramientas? ¿Por qué es único e innovador?

- **No es un simple visor de retrasos.** La mayoría de apps ferroviarias solo muestran horarios y retrasos. Esta herramienta **detecta activamente situaciones de peligro** y genera alertas en tiempo real.
- **Enfoque en seguridad, no en información al pasajero.** El objetivo no es saber si el tren llega tarde, sino **evitar que dos trenes colisionen** cuando uno se ha detenido en vía.
- **Alerta sonora continua e insistente.** Como en una cabina de avión, la alarma no se silencia sola; requiere reconocimiento humano. Esto evita que una alerta crítica pase desapercibida.
- **Detección de trenes detenidos "lejos de estación".** Este es el núcleo del sistema: no basta con que un tren vaya lento; tiene que estar en un tramo donde no debería detenerse.
- **Tramos cortados automáticos.** Si se detecta un posible accidente, el sistema cierra la vía virtualmente y avisa a los trenes que se aproximan, sin intervención humana.
- **Memoria de 30 días.** Permite auditoría y análisis posterior.
- **Código abierto y modular.** Cualquiera puede revisarlo, mejorarlo o adaptarlo.

**En resumen: no existe nada así en el mercado público.** Ni Renfe ni Adif ofrecen una herramienta de este tipo a los ciudadanos. Y aunque existen sistemas internos de seguridad (ASFA, ERTMS), no están al alcance del público ni son de código abierto. **Esta es una prueba de concepto de lo que la tecnología abierta puede hacer por la seguridad ferroviaria.**
![TheCondor](Telemetria.pnj)

## ⚠️ Aviso Importante: Es un Prototipo (No sustituye nada)

**Este es un prototipo funcional. No está terminado.**

- **NO sustituye** a los sistemas de seguridad ferroviaria oficiales (ASFA, ERTMS, etc.).
- **NO sustituye** a los maquinistas ni a los sistemas de señalización de Renfe o Adif.
- **NO es una herramienta de producción.** Es una prueba de concepto que usa datos públicos y heurísticas.
- Los datos de posición pueden tener retraso o errores. Los tramos automáticos son aproximados.
- La seguridad ferroviaria real requiere hardware certificado, protocolos estrictos y validación humana. Esto es solo una herramienta de apoyo y concienciación.

## 🤝 ¿Por qué la comunidad debería trabajar en esto? (Código abierto para el bien común)

**La publico precisamente para eso: para que otros puedan hacer algo con ella, agregar mejoras y llevarla más lejos.** Porque la seguridad no debería depender de que una sola persona tenga todas las respuestas. Este es el punto de partida. El siguiente paso lo damos entre todos.

Creo firmemente que la seguridad ferroviaria es un **bien común**. No debería ser un secreto industrial ni un privilegio de unos pocos. Si esta herramienta puede salvar una vida, aunque sea en una fracción de prueba, ya habrá valido la pena. Pero para que sea realmente útil, necesita crecer, ser revisada, criticada y mejorada por la comunidad.

**Quien quiera, que participe. Que lo agarre, lo mejore y lo adapte.** No busco protagonismo; busco que la idea viva y evolucione.

### Ideas para futuras mejoras (¡anímate a contribuir!):

1. **Integración de GPS y Bluetooth:** Para que el sistema nunca se quede sin señal. Si un tren pierde la cobertura GPS, el sistema podría usar balizas Bluetooth o sensores de proximidad para seguir detectando la posición y el estado de los trenes. (Yo mismo intentaré hacerlo, pero no sé si llegaré; por eso lo dejo aquí).
2. **Datos de Adif en tiempo real:** Integrar una API oficial de incidencias (si se abre al público) para cruzar datos y mejorar la precisión de los tramos cortados.
3. **Modelos predictivos:** Usar machine learning para predecir paradas no programadas antes de que ocurran, analizando patrones históricos.
4. **Interfaz móvil:** Una app ligera para que los maquinistas o supervisores reciban las alertas en el móvil.
5. **Validación con datos históricos:** Probar el sistema con datos de accidentes pasados para calibrar los umbrales y mejorar la detección.
6. **Integración con hardware:** Conectar el sistema a sensores físicos (acelerómetros, GPS diferencial) para mayor precisión.

## 🛠️ Instalación y Uso

### Requisitos
- Python 3.9 o superior.
- Conexión a Internet (para obtener datos de Renfe).
- Navegador web moderno (Chrome, Firefox, Edge).

### Instalación
```bash
pip install streamlit streamlit-folium streamlit-autorefresh folium pandas numpy requests
```

### Ejecución
```bash
streamlit run renfealarm.py
```

### Configuración (opcional)
Puedes configurar canales de aviso mediante variables de entorno o `st.secrets`:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `NTFY_TOPIC`, `NTFY_SERVER`
- `ALERT_WEBHOOK_URL`
- `ADIF_INCIDENTS_URL` (JSON con avisos de Adif)
- `EBM_DB` (ruta de la base de datos SQLite)
- `CARTO_API_KEY` (para mapas base)

## 🙏 Créditos y Méritos

- **Datos públicos:** A Renfe y Adif por proporcionar los datos de posición de trenes y estaciones a través de sus visores públicos. Sin ellos, esto no sería posible.
- **Tecnología:** Streamlit, Folium, Pandas, Numpy, SQLite.
- **Inspiración:** Al chico que se cansó de las críticas. Y a todos los maquinistas que, como última opción, accionaron el freno.
- **Comunidad:** A todos los que creen que la tecnología debe estar al servicio de la seguridad y el bien común.


## 📄 Licencia

Este proyecto se distribuye bajo la licencia **MIT**. Eres libre de usarlo, modificarlo y distribuirlo, siempre que se mantenga el aviso de copyright y se reconozca la autoría original.

---

> **"Que la alarma suene antes de que la única opción sea accionar el freno a mano."**
> -CONDOR2026
