# 🤝 Cómo contribuir a Emergency Brake Monitor (A.M.D.C.)

¡Gracias por querer participar! Este es un proyecto de **código abierto** y **necesita de la comunidad** para crecer. Pero antes de empezar, es importante que tengas claro el espíritu del proyecto: **no buscamos lucro, buscamos seguridad, concienciación y bien común.**

Si estás de acuerdo con la línea ética descrita en el `DISCLAIMER.md` y con la licencia **CC BY-NC-SA 4.0** (que prohíbe el uso comercial y obliga a compartir igual), adelante. Aquí tienes algunas formas de ayudar:

## 1. Antes de contribuir: lee el DISCLAIMER y la licencia
Este proyecto tiene una **línea ética y legal muy clara** (puedes leerla en el archivo `DISCLAIMER.md`). **No se aceptarán contribuciones** que:
- Promuevan usos ilegales, fraudulentos o engañosos.
- Busquen manipular o sabotear sistemas ferroviarios reales.
- Generen alertas falsas o alarmas injustificadas.
- Difamen, acosen o perjudiquen a personas o instituciones.
- Vayan en contra del respeto hacia las víctimas y los profesionales del sector.
- Pretendan **vender el software, ofrecerlo como servicio de pago o incluirlo en un producto comercial** (la licencia CC BY-NC-SA 4.0 lo prohíbe expresamente).

**Al enviar una contribución (Pull Request), aceptas que tu código se distribuya bajo la misma licencia CC BY-NC-SA 4.0** y que se mantenga la línea ética del proyecto.

## 2. Reportar errores o sugerir mejoras
Abre un **Issue** en GitHub explicando:
- Qué esperabas que pasara.
- Qué pasó realmente.
- Pasos para reproducirlo (si es un error).
- Capturas de pantalla o logs (si es posible).
- Si es una sugerencia, explica por qué crees que es útil y cómo encaja con la línea ética del proyecto.

**Importante:** No publiques datos personales, credenciales reales ni información sensible en los Issues.

## 3. Enviar código (Pull Requests)
Si has mejorado algo, ¡anímate a enviar un **Pull Request**! Antes de hacerlo:
- Asegúrate de que el código funciona y no rompe lo existente.
- Explica en la descripción del PR qué cambiaste y por qué.
- Si es una mejora grande, ábrelo primero como Issue para discutirlo.
- **Respeta la línea ética y la licencia del proyecto.** Si tu PR va en contra del `DISCLAIMER.md` o de la CC BY-NC-SA 4.0, será rechazado.
- No incluyas código malicioso, ofuscado o que realice acciones no documentadas.
- **No incluyas dependencias que tengan licencias incompatibles** con la CC BY-NC-SA 4.0 (por ejemplo, licencias que permitan el uso comercial cerrado).

## 4. Probar y validar (¡muy necesario!)
El proyecto es un prototipo y **necesita validación real**. Aquí tienes algunas áreas donde puedes ayudar:
- **Canales de notificación:** El código de Telegram, ntfy y webhooks está implementado, pero **NO ha sido probado en un entorno real**. Si tienes experiencia con bots, prueba a configurarlo y reporta si funciona o no.
- **Datos reales:** Prueba el sistema en diferentes horarios y condiciones para ver cómo se comporta.
- **Casos límite:** ¿Qué pasa si el feed se congela? ¿Y si hay muchos trenes detenidos a la vez? ¿Y si la conexión a Internet falla?
- **Rendimiento:** ¿El sistema consume muchos recursos? ¿Se ralentiza con muchos trenes?
- **Autodiagnóstico:** Ejecuta la pestaña CALIBRAR y comprueba que todas las pruebas pasan con tu calibración.
- **Simulador:** Prueba el tren SIM-001 y verifica que las reglas de detección responden como se espera.

## 5. Ideas futuras (roadmap abierto)
Estas son algunas ideas para mejorar el proyecto. Si te animas con alguna, ¡adelante!
- **Integración de GPS y Bluetooth:** Para que el sistema nunca se quede sin señal (si un tren pierde GPS, usar balizas Bluetooth o sensores de proximidad).
- **Datos de Adif en tiempo real:** Integrar una API oficial de incidencias (si se abre al público) para cruzar datos.
- **Modelos predictivos:** Usar machine learning para predecir paradas no programadas antes de que ocurran.
- **Interfaz móvil:** Una app ligera para que maquinistas o supervisores reciban alertas en el móvil.
- **Validación con datos históricos:** Probar el sistema con datos de accidentes pasados para calibrar los umbrales.
- **Integración con hardware:** Conectar el sistema a sensores físicos (acelerómetros, GPS diferencial) para mayor precisión.
- **Documentación:** Mejorar la documentación, añadir tutoriales o vídeos explicativos.

## 6. Difundir
Si el proyecto te parece interesante, compártelo con personas que puedan aportar. La seguridad ferroviaria es un bien común y cuanta más gente lo conozca, mejor. Pero **difúndelo siempre con respeto** hacia las víctimas y los profesionales del sector.

## 7. Código de conducta
Este proyecto sigue un **Código de Conducta** sencillo: sé respetuoso, acepta críticas constructivas, muestra empatía y no toleres el acoso ni los insultos. Puedes leerlo completo en el archivo `CODE_OF_CONDUCT.md`.

---

**Recuerda:** Este es un prototipo. No sustituye a los sistemas oficiales. Úsalo con responsabilidad y respeto.

> **"Que la alarma suene antes de que la única opción sea accionar el freno a mano."**
> 
> *— En memoria de las víctimas y de los maquinistas que, como última opción, accionaron la palanca del freno.*
> 
> **— Condor2026**
