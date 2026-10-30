# HALLAZGOS — Cliente API SIGAH

> **Estado:** borrador vivo. Observaciones del 28 y 29-10-2026 contra producción: lecturas con `GET` y
> escrituras **solo sobre las 3 citas reservadas por Informática para pruebas** (§1.4), más una captura
> de la interfaz de SIGAH 4.2 enviada por Jorge (Informática) el 29-10.
> Manual de referencia: "Manual de Interfaz de Integración (API REST)", v1.4.
> Ningún dato de paciente se copia en este documento.

---

## 1. Diferencias entre el manual y el sistema real

| # | Tema | Manual | Sistema real | Impacto |
|---|---|---|---|---|
| 1 | Autenticación | `Authorization: Bearer <key>` | Cabecera `X-Auth-Token: <key>` | Sin esto no hay conexión |
| 2 | Códigos HTTP de error | 400 / 401 / 500 | Errores de negocio con **HTTP 200** y `{"estado":"ERROR","codigo":...,"msg":...}` | 🔴 Hay que leer el cuerpo, no solo el HTTP |
| 3 | Credencial expirada | 401 | **403** `ERR-01 "credencial expirada"`. Key inválida: 401 `"credencial no reconocida"` | El mismo `ERR-01` cubre casos distintos |
| 4 | Códigos de error | `ERR-01`, `ERR-02` | Además **`ERR-03 "token de continuacion invalido"`**, **`ERR-04 "no existe"`**, y en escrituras **`ERR-07`** (re-confirmar una confirmada) y **`ERR-09`** (confirmar una cancelada) | Hay códigos no documentados |
| 5 | Errores de infraestructura | — | **502 Bad Gateway intermitentes**, en HTML de nginx (no JSON). Al reintentar, la misma petición responde bien | 🟠 Hacen falta reintentos en las lecturas |
| 6 | Ruta inexistente | — | 404 `{"detail":"Not Found"}`, un tercer formato de error | — |
| 7 | `centro_id` | Opcional (centro por defecto según la key) | **Obligatorio**: sin él, `ERR-02 "parametros insuficientes"`. Según Jorge, el **centro 3 es el Hospital**, y es el único con datos (se probaron 0, -1 y del 1 al 100 en distintos puntos). **Un centro inexistente responde `OK` con 0 citas**, igual que un centro sin agenda. No hay endpoint de catálogo (`/centros` → 404) | 🟠 Un `centro_id` equivocado da una agenda vacía silenciosa |
| 7b | Validación de parámetros | — | `centro_id=abc` → **HTTP 422** con el formato de validación de FastAPI (`{"detail":[...]}`), un cuarto formato de error. `centro_id=3.0` se acepta como 3 | — |
| 8 | `fecha` | `YYYY-MM-DD HH:MM:SS` | Sin la parte de hora (`2026-10-28`) devuelve **`OK` con 0 citas, sin error**. La hora se ignora (`00:00:00` y `12:00:00` dan lo mismo) | 🔴 Agenda vacía falsa |
| 9 | **Zona horaria** | Hora local, sin zona | **`FEC_HORA` = hora local + 4 h** (ver §1.1). No es hora local, ni tampoco UTC real (en diciembre, Chile está en UTC-3) | 🔴 Hora equivocada al paciente y citas en el día equivocado |
| 10 | Forma de la respuesta | Lista JSON | `{"estado":"OK","total":N,"citas":[...]}`. Detalle: `{"estado":"OK","cita":{...}}` | — |
| 11 | Nombres de campos | `id, rut, nombre, fechaHora, estado, especialidad, profesional, telefono, email` | `ID_CITA, RUT_PAC, NOM_PAC, FEC_HORA, COD_EST, COD_PRO, NOM_PRO, MEDICO, CENTRO, TEL_PAC, OBS` | Todos distintos |
| 12 | Id de cita | Entero (`10432`) | Texto (`"AGD-0000010168"`). `/citas/10168` responde `ERR-04` | — |
| 13 | Estado | Texto: `AGENDADA` / `CONFIRMADA` / `CANCELADA` | **Número** `COD_EST`: **`1 = AGENDADA`** (contrastado con la interfaz), **`2 = CONFIRMADA`** y **`3 = CANCELADA`** (observados al escribir, §1.4) | 🟠 Puede haber otros (ej. atendida, no asistió) |
| 14 | Filtro `estado` | Filtra por estado | **Se ignora**: `estado=CONFIRMADA` devuelve las citas con `COD_EST=1` | 🟠 Hay que filtrar del lado del cliente |
| 15 | Paginación | v1.4: "se incorpora paginación (ver Anexo B)" | **El Anexo B no existe.** Jorge confirma que hay paginación. Es por **token de continuación** en el parámetro **`desde`**. Ninguna respuesta observada trajo token (máximo 20 citas por día). Unos 20 parámetros de tamaño de página o de rango de fechas se ignoran. Detalle en §1.2 | 🔴 No sabemos en qué campo viene el token |
| 16 | Especialidad | Nombre (`"Traumatología"`). Anexo A con 5 códigos | Código (`COD_PRO`) y nombre en mayúsculas sin tildes (`NOM_PRO`). Aparece **`URGE`** (Urgencia Ambulatoria), que no está en el catálogo | — |
| 17 | `email` | Existe (puede venir `null`) | **No existe.** Aparece `OBS` | No hay canal alternativo al teléfono |
| 18 | `OBS` | — | **Siempre `null` en la API**, aunque en la interfaz 3 citas tienen la observación "RESERVA INFORMATICA · PRUEBA INTEGRACION" | 🟠 La API no expone las observaciones; las citas de prueba no se pueden identificar por API |
| 19 | Formatos | ISO `2026-10-06T08:00:00`, RUT sin puntos, teléfono `+569XXXXXXXX`, nombre "Nombres Apellidos" | Fecha con espacio, RUT con puntos, teléfono con espacios (`+56 9 XXXX XXXX`), nombre `"APELLIDOS, NOMBRES"` en mayúsculas | Hay que normalizar |
| 20 | Ambiente QA | "En revisión" | No existe. Informática reservó **3 citas de prueba en producción** (15-12-2026); "el resto de la agenda no se debe modificar" | Escritura solo sobre esas 3 (§3.1) |
| 21 | Versión del manual | v1.4 (04-2021) | El documento tiene fecha 14-08-2019 (la de la v1.3) y "Revisado por: (pendiente)". Los cambios de la v1.4 (paginación, fechas) no están descritos | Todo el manual es sospechoso |
| 22 | Respuesta de `confirmar` / `anular` | No documentada | **Texto plano, no JSON**: `OK` si se aplica, `ERR-xx` si se rechaza, ambos con **HTTP 200** | 🔴 Un cliente que espera JSON informa error en una escritura exitosa |
| 23 | Latencia de las escrituras | — | **Muy variable: de 0.02 s a 25 s** (§1.4). La primera confirmación no respondió en 10 s y el cambio apareció entre 10 y 27 s después de enviarla; una relectura inmediata al timeout todavía mostraba la cita agendada. Anular una cita confirmada tardó 25 s | 🔴 Un reintento automático habría confirmado dos veces |

### 1.4 Pruebas de escritura (29-10-2026)

Sobre las citas reservadas por Informática (§3.2), con autorización explícita. Cada escritura se precedió de una relectura que verificaba fecha, hora, especialidad y centro.

| Paso | Cita | Acción | Resultado |
|---|---|---|---|
| A1 | 099013 (agendada) | `confirmar` (cliente, timeout 10 s) | Timeout sin respuesta; el cliente informó **resultado incierto** y no reintentó. La relectura inmediata mostraba `COD_EST=1`; ~17 s después, `COD_EST=2` |
| A2 | 099013 (confirmada) | `confirmar` otra vez (POST directo) | HTTP 200, al instante, cuerpo `ERR-07`. Estado sin cambios |
| B1 | 099014 (agendada) | `anular` (cliente) | HTTP 200 en 20 ms, cuerpo `OK`, `COD_EST=3`. El cliente lo informó como error por no ser JSON: **corregido** |
| B2 | 099014 (cancelada) | `confirmar` (POST directo) | HTTP 200, cuerpo `ERR-09`. Estado sin cambios: SIGAH valida transiciones |
| B3 | 099013 (confirmada) | `anular` (cliente corregido) | `OK` **tras 25 s**, `COD_EST=3`. Flujo completo correcto; con el timeout original de 10 s habría sido "incierto" |
| — | 099015 | No se tocó | Queda de reserva |

Las otras 17 citas del 15-12 siguen agendadas. Los cuerpos de texto plano se identificaron comparando el SHA-256 guardado en la auditoría con candidatos (`OK`, `ERR-00`…`ERR-99`), sin guardar respuestas en claro.

### 1.1 Evidencia del desfase horario de +4 h

La interfaz de SIGAH indica explícitamente "Horas en hora local del establecimiento". Comparación de la misma agenda:

| | Interfaz (hora local) | API (`FEC_HORA`) |
|---|---|---|
| 15-12-2026, Medicina Interna, 20 citas | 08:00 → 17:30, cada 30 min | 12:00 → 21:30, cada 30 min |

- Desfase: **+4 h**. En diciembre Chile continental está en **UTC-3** (horario de verano), así que UTC real daría +3 h.
- Hipótesis: el servidor convierte a "UTC" con un **desfase fijo de -4 h** (hora estándar de Chile) e ignora el horario de verano. Sería consistente con los "ajustes en el manejo de fechas" de la v1.4.
- Coincide con octubre: la API entrega 12:00–22:00 más 00:30, que en local es **08:00–18:00 más una urgencia a las 20:30 del día anterior**. Por eso la consulta del lunes 26 no trae la cita de las 00:30 y la del sábado 31 trae solo esa (la del viernes 30 por la noche).
- **No se puede verificar el comportamiento en invierno (abril–septiembre)**: no hay datos en ese período.
- *Corrección:* en un borrador anterior supusimos UTC-3 a partir del horario. La captura de la interfaz lo desmiente.

### 1.2 Comportamiento del parámetro `desde` (paginación)

| Valor de `desde` | Respuesta |
|---|---|
| vacío | Igual que sin el parámetro |
| `0`, `5`, `99010`, base64 (`MTA=`, `{"offset":10}`) | `ERR-03 "token de continuacion invalido"` |
| `AGD-0000000000` | Las 20 citas (como sin token) |
| `AGD-0000099001`, `AGD-0000099010` (ids reales del día) | **`OK` con `total: 0`** |

- Un id con formato `AGD-…` pasa la validación, pero no funciona como "continuar después de este id" (con `099001` deberían quedar 19 citas).
- **`total` cambia según el token**, así que no es el total del día. El control `total` vs. cantidad recibida no basta para detectar páginas faltantes.
- **Un token incorrecto puede responder "OK, 0 citas"**: otra agenda vacía silenciosa.
- Conclusión: el token es opaco y **no se puede deducir sin una respuesta real que lo traiga**. Adivinarlo arriesga datos incompletos. Se le pregunta a Jorge.

### 1.3 La agenda de la captura corresponde al centro 3

La captura dice "Consultorio Adosado" y Jorge dice que el centro 3 es "el Hospital". Para verificar que se trata de la misma agenda, se comparó la estructura sin exponer datos:

- **Diferencias entre RUT consecutivos** (ordenados por hora): en la captura, 18 saltos de 1 y uno final de 10. En la API, centro 3, 15-12: **idénticas**. Lo mismo ocurre con los teléfonos.
- Un solo profesional, Medicina Interna y 20 citas en ambos casos.
- Las filas reservadas para pruebas (13, 14 y 15 en la captura) corresponden en la API a las posiciones 13, 14 y 15, a las 18:00, 18:30 y 19:00, en línea con el desfase de +4 h.
- Lectura probable: el *Consultorio Adosado de Especialidades* es la unidad ambulatoria del Hospital, por lo que comparte el centro 3.

---

## 2. Calidad de datos observada

Datos existentes: solo del **26 al 31-10-2026** (60 citas, 6 especialidades) y del **15-12-2026** (20 citas, Medicina Interna). Nada antes, nada entremedio, nada después.

| Verificación | Resultado |
|---|---|
| `ID_CITA` únicos | ✅ Sin repetidos |
| Dígito verificador del RUT válido (oct.) | **6/60**. En la interfaz, todos los RUT terminan en `-5`, así que es un problema de origen |
| Pacientes distintos (oct.) | **20**: cada uno con 3 citas en la semana |
| Paciente con más de una cita el mismo día | 0 |
| Médico con dos citas a la misma hora | 0 |
| Teléfono con formato de móvil chileno | 100 % |
| `COD_PRO` ↔ `NOM_PRO` consistentes | ✅ |
| Lista vs. detalle (`/citas/{id}`) | Mismos campos y valores |
| ¿Los GET modifican datos? | No en lo visible: el SHA-256 de 4 respuestas es idéntico antes y después de 12 consultas repetidas. Un efecto interno no expuesto por la API (ej. "último acceso") no es verificable |
| API vs. interfaz (15-12) | Misma cantidad (20), especialidad, profesional y estado. Hora +4 h. `OBS` no aparece en la API |

---

## 3. Decisiones y supuestos

| Decisión | Por qué |
|---|---|
| **Modelo propio** (`Cita`, `EstadoCita`) con un traductor desde los campos SIGAH | El resto de la plataforma no debe conocer `NOM_PAC` ni `COD_EST` |
| **Se valida el cuerpo, no solo el HTTP**: `estado != "OK"` → excepción tipada según `codigo` | Los errores llegan con HTTP 200 |
| **Paginación por token en `desde`**. Si `total` no coincide con la cantidad de citas acumuladas → error, no un resultado parcial | Mientras no sepamos dónde viene el token, es mejor fallar que entregar una agenda incompleta |
| **Ante agenda vacía, se valida el formato de `fecha`** antes de enviar | `fecha` sin hora devuelve "OK, 0 citas" falso |
| **Desfase de `FEC_HORA` configurable, por defecto +4 h**. Se expone en hora local con zona (`America/Santiago`) | Evidencia en §1.1. Configurable porque no conocemos el comportamiento en invierno |
| **"Agenda de un día local" = pedir dos días de la API y filtrar por fecha local** | Las citas locales después de las 20:00 caen en el día siguiente de la API |
| **`COD_EST`: `1 → AGENDADA`, `2 → CONFIRMADA`, `3 → CANCELADA`. Cualquier otro valor → `DESCONOCIDO`**, nunca se adivina | 1 contrastado con la interfaz; 2 y 3 observados en las pruebas de escritura |
| **Respuestas en texto plano**: `OK` es éxito; `ERR-xx` se convierte en la excepción del código | Así responden `confirmar` y `anular` (§1.4) |
| **Timeout de escritura propio (60 s)**, separado del de lectura (10 s) | La confirmación tardó más de 10 s en producción |
| **El filtro por estado se aplica en el cliente** | El servidor lo ignora |
| **Reintentos solo en GET** (502/503/504, timeout, error de conexión) con backoff | Los 502 son intermitentes. Las lecturas son seguras de repetir |
| **POST nunca se reintenta automáticamente.** Ante timeout se consulta `GET /citas/{id}` y se reporta "resultado incierto" | Anular notifica al paciente: repetirlo puede duplicar el efecto |
| **Antes de confirmar o anular se vuelve a leer la cita** y se verifica su estado | El estado puede cambiar entre la descarga de la mañana y la llamada |
| **Normalización**: RUT sin puntos con DV en mayúscula, teléfono en E.164, nombre separado en apellidos y nombres | Datos con formatos distintos al manual |
| **Un dato inválido (RUT con DV malo, teléfono no interpretable) no descarta la cita**: queda marcada con una advertencia | Excluir citas dejaría pacientes sin su llamada. Mejor completa y marcada |
| **Centro 3 (Hospital) por defecto**, configurable con `SIGAH_CENTRO_ID` | Confirmado por Informática y único con datos. Un centro equivocado responde "OK, 0 citas" sin error, por eso el valor está documentado y no se deduce |
| **Solo la API key es obligatoria**; URL, centro, desfase, timeouts y horarios tienen valores por defecto como constantes con nombre y motivo | Requisito: clonar, configurar la key y obtener la agenda |
| **Auditoría en SQLite de toda llamada (GET y POST)**: URL, HTTP, `x-cloud-trace-context`, cuerpo completo **con datos personales enmascarados** (lista blanca de campos) y SHA-256 del cuerpo original. En escrituras se registra además la intención antes de enviar | Evidencia ante incidentes sin guardar una copia de los datos de pacientes |
| **Log de calidad** (`logging`, logger `sigah.calidad`): un aviso por dato inválido, con el id de la cita y sin valores personales | La plataforma decide dónde guardarlo |
| **Escritura doblemente protegida**: la librería la trae deshabilitada y el CLI solo escribe sobre ids listados en `SIGAH_IDS_ESCRIBIBLES` | En producción, solo las 3 citas de prueba deben poder modificarse |
| **Reglas de negocio separadas del cliente** (`reglas.revisar`): devuelven alertas sin modificar ni descartar citas | La plataforma decide qué hacer con cada alerta |
| **Sin BD de agenda ni cron** | El alcance es el cliente. Programar la ejecución y guardar la agenda le corresponde a la plataforma |

### 3.1 Reglas de negocio (alertas)

| Alerta | Cuándo |
|---|---|
| `paciente_misma_hora` | Mismo RUT, mismo inicio |
| `paciente_misma_especialidad_dia` | Mismo RUT, misma especialidad, mismo día |
| `sin_contacto` | Sin teléfono válido (el único canal de contacto) |
| `estado_desconocido` | `COD_EST` no catalogado |
| `horario_fuera_de_rango` | Inicio fuera de `SIGAH_HORA_MIN`–`SIGAH_HORA_MAX` (07:00–21:00 por defecto). También avisa si el desfase horario cambia |
| `cita_pasada` | Inicio anterior al momento de la revisión |
| `profesional_misma_hora` | **Opcional, apagada por defecto** (`SIGAH_REVISAR_PROFESIONAL=true`). Mismo profesional, mismo inicio, excluye equipos ("EQUIPO …") |

Limitaciones:
- SIGAH no informa la **duración** de las citas: solo se detectan inicios idénticos, no solapamientos.
- El profesional viene **solo como nombre abreviado** ("DRA. ROJAS I."), sin id: dos médicos homónimos generarían falsos positivos. Por eso esa regla es opcional.
- Los pacientes se identifican por RUT. Una cita sin RUT válido no participa en las reglas de paciente.

### 3.2 Citas de prueba para escritura

Según la interfaz, Informática reservó 3 citas el 15-12-2026 (Medicina Interna, centro 3), a las **14:00, 14:30 y 15:00 hora local**. En la API corresponden a:

| Hora local | `FEC_HORA` API | `ID_CITA` |
|---|---|---|
| 14:00 | 18:00 | `AGD-0000099013` |
| 14:30 | 18:30 | `AGD-0000099014` |
| 15:00 | 19:00 | `AGD-0000099015` |

- La asociación coincide por **dos vías independientes**: el desfase horario (§1.1) y la posición de los pacientes en la secuencia (§1.3).
- La API no expone la observación que las marca, así que no hay confirmación directa. Como se trata de escribir en producción, se pide a Jorge una confirmación de una línea antes de la primera escritura.
- El CLI solo permite escribir sobre ids listados en `SIGAH_IDS_ESCRIBIBLES`.
- Estado tras las pruebas (§1.4): `099013` y `099014` canceladas; `099015` agendada, sin usar.

---

## 4. Preguntas abiertas (para Jorge)

| # | Pregunta | Estado |
|---|---|---|
| 1 | Desfase de `FEC_HORA` | ✅ Resuelto con evidencia (+4 h, §1.1); no se pregunta. Riesgo de invierno documentado (§5) |
| 2 | Lista completa de valores de `COD_EST` y su significado | Parcial: 1, 2 y 3 conocidos (§1.4). ¿Hay otros? |
| 3 | Paginación: ¿en qué campo viene el token para `desde`? ¿Cuál es el tamaño de página? | Parcial: Jorge confirma que existe; el parámetro `desde` lo encontramos nosotros (§1.2) |
| 4 | Lista completa de centros | Parcial: centro 3 = Hospital (Jorge), y la agenda de la captura es la del centro 3 (§1.3). Es el único con datos |
| 5 | ¿Qué responden `confirmar` y `anular`? ¿Qué transiciones de estado se permiten? ¿Es idempotente confirmar dos veces? | ✅ Resuelta con pruebas (§1.4). Abierto: ¿por qué la confirmación tarda más de 10 s? ¿Es asíncrona? |
| 6 | ¿Anular las citas de prueba gatilló notificaciones a los teléfonos registrados? | Pendiente: se anularon 2 citas de prueba (§1.4) |
| 7 | Lista completa de códigos de error y su significado (vistos: `ERR-01` a `ERR-04`, `ERR-07`, `ERR-09`) | Pendiente |
| 8 | ¿Los datos son reales? RUT con DV inválido, pacientes repetidos, agenda solo en 7 días | Pendiente |
| 9 | Catálogo completo de especialidades (`URGE` no está en el Anexo A) | Pendiente |
| 10 | `OBS` sale `null` en la API, aunque en la interfaz tiene contenido. ¿Es un campo distinto? | Pendiente |
| 11 | Vigencia de la API key y proceso de renovación | ✅ Resuelta: nueva key entregada |

---

## 5. Riesgos antes de producción

1. **Desfase horario sin confirmar.** Si se interpreta mal, se le informa al paciente una hora equivocada y algunas citas quedan en el día equivocado. El comportamiento en invierno es desconocido.
2. **Estados posiblemente incompletos.** Conocemos 1, 2 y 3. Cualquier otro código queda como `DESCONOCIDO`: la plataforma no debe llamar ni escribir sobre esas citas sin revisión.
3. **Paginación sin campo de token conocido.** Con más de 20 citas por día (lo normal en un hospital) podría haber páginas que no vemos. `total` no sirve como control fiable (§1.2). El cliente falla con un error explícito ante cualquier campo de respuesta desconocido, porque podría ser el token.
4. **Confirmación lenta o asíncrona.** Si `confirmar` supera el timeout, el resultado es incierto y una relectura inmediata puede no reflejarlo todavía. La plataforma debe revisar esos casos más tarde, nunca reintentarlos a ciegas.
5. **Las citas de prueba no se distinguen por API.** Para nuevas pruebas, pedir a Informática ids explícitos.
6. **Inestabilidad.** Hay 502 intermitentes. Si coinciden con un POST, el resultado es incierto y queda en la auditoría para revisión manual.
7. **Agenda vacía silenciosa.** Una petición mal formada puede responder "OK, 0 citas". Conviene alertar en la plataforma cuando un día hábil viene vacío.
8. **Datos personales y de salud.** La auditoría y los logs no deben guardar datos de pacientes en claro; aplica la Ley 19.628 / Ley 21.719.
9. **Solo hay canal telefónico.** No hay email: una cita con teléfono inválido no tiene forma de contacto y debe reportarse.
10. **Manual no confiable.** Cualquier cambio del proveedor puede romper el mapeo: el traductor falla de forma explícita ante campos faltantes en vez de rellenar con vacíos.

---

## 6. Cómo se verificó

- Lecturas con `GET`, con volumen bajo (unas 150 llamadas en total) y salida enmascarada (sin datos personales).
- 5 escrituras, solo sobre 2 de las 3 citas reservadas para pruebas (§1.4), todas auditadas.
- Fechas consultadas: 01-10, 13-10, 19-10 al 31-10, varias de noviembre y diciembre, incluido el 15-12-2026. Centros 1 al 10.
- Rutas probadas: `/citas` (con variantes de `fecha`, `centro_id`, `estado` y unos 20 nombres de parámetros de paginación), `/citas/{id}` (id válido, inexistente y numérico) y rutas de documentación (`/docs`, `/openapi.json`), que no existen.
- Contraste con la captura de la interfaz de SIGAH 4.2 (agenda del 15-12-2026) enviada por Jorge.
