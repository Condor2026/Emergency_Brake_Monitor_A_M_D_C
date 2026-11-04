
# 🔒 Política de Seguridad
**Emergency Brake Monitor (A.M.D.C.) — Condor2026**

## 1. Alcance de la seguridad

Este es un **prototipo experimental de código abierto**. No es un producto comercial, no ha sido auditado por expertos en ciberseguridad y no cuenta con certificaciones de seguridad.

**Limitaciones conocidas:**
- **Los canales de notificación (Telegram, ntfy, webhooks) NO han sido probados en un entorno real.** La lógica de envío está implementada, pero no se ha validado con credenciales reales ni con servidores en producción. Podrían existir fallos de seguridad no detectados.
- La base de datos SQLite es local y no está cifrada. Si almacenas datos sensibles, hazlo bajo tu propia responsabilidad.
- El sistema utiliza datos públicos de Renfe/Adif y heurísticas de cálculo. **Los datos pueden tener retraso, errores o estar incompletos.**
- La interfaz web (Streamlit) está pensada para uso local o en entornos controlados. **No la expongas directamente a Internet sin las debidas protecciones** (autenticación, HTTPS, firewall, etc.).
- La licencia **CC BY-NC-SA 4.0** prohíbe el uso comercial. Cualquier uso que viole esta licencia no está autorizado y queda fuera de la responsabilidad del autor.

**Este software NO sustituye a los sistemas de seguridad ferroviaria oficiales.** No lo uses como única fuente para tomar decisiones críticas.

## 2. Cómo reportar una vulnerabilidad

Si encuentras un problema de seguridad en este proyecto (por ejemplo, una forma de inyectar código, exponer datos sensibles, manipular las alertas o eludir la lógica de detección), **NO lo publiques en un Issue abierto**.

Por favor, sigue este procedimiento:
1. **Envía un correo electrónico** a [tu-email@ejemplo.com] con el asunto `[SECURITY] Emergency Brake Monitor`.
2. **O utiliza la función de Security Advisories de GitHub** (si está habilitada en el repositorio).
3. Incluye una descripción detallada del problema, los pasos para reproducirlo y, si es posible, una prueba de concepto (PoC).
4. **No divulgues públicamente la vulnerabilidad** hasta que se haya solucionado y se haya dado el permiso correspondiente.

**Compromiso del autor:** Todas las quejas serán revisadas e investigadas de forma confidencial. Se intentará dar una respuesta en un plazo razonable (aunque no se garantiza un tiempo específico, al ser un proyecto personal). Si la vulnerabilidad es confirmada, se trabajará en una solución y se te dará el crédito correspondiente (si así lo deseas).

## 3. Buenas prácticas para usuarios y colaboradores

- **No uses credenciales reales en entornos públicos.** Si pruebas los canales de notificación, usa tokens de prueba o datos ficticios.
- **Prueba los canales de notificación con datos ficticios** antes de usarlos en producción.
- **Mantén actualizadas las dependencias** (Streamlit, Folium, Pandas, etc.) para evitar vulnerabilidades conocidas.
- **No expongas la interfaz web a Internet** sin autenticación, HTTPS y firewall. Si usas `EBM_PASSWORD`, asegúrate de que sea una contraseña fuerte.
- **No utilices el sistema para generar alarmas falsas** o para causar pánico. Eso va en contra de la línea ética del proyecto (ver `DISCLAIMER.md`).
- **Revisa el código** antes de ejecutarlo en tu entorno. Es código abierto, pero eso no significa que sea seguro por defecto.
- **Respeta la licencia CC BY-NC-SA 4.0.** No vendas el software, no lo ofrezcas como servicio de pago ni lo incluyas en un producto comercial.

## 4. Divulgación responsable

Si has encontrado una vulnerabilidad y quieres divulgarla públicamente, **espera a que se haya solucionado** y coordina con el autor. La divulgación responsable ayuda a proteger a los usuarios y a mejorar el proyecto.

## 5. Agradecimientos

Agradecemos a todas las personas que dedican su tiempo a revisar el código y reportar problemas de seguridad de forma responsable. Vuestras contribuciones ayudan a que este proyecto sea más seguro y útil para todos.

---

> **"Que la alarma suene antes de que la única opción sea accionar el freno a mano."**
> 
> *— En memoria de las víctimas y de los maquinistas que, como última opción, accionaron la palanca del freno.*
> 
> **— Condor2026**
