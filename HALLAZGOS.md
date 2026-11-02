# HALLAZGOS — Cliente API SIGAH

> Trabajo del 27 al 31-10-2026 contra el ambiente entregado (producción del hospital): lecturas con `GET` y
> escrituras **solo sobre las 3 citas que Informática reservó para pruebas** (§1.4). Incluye el contraste con una
> captura de la interfaz de SIGAH 4.2 enviada por Informática. Manual de referencia: "Manual de Interfaz de
> Integración (API REST)", v1.4. Ningún dato de paciente se copia en este documento.

## Resumen

- **El manual no describe el sistema real**: autenticación, nombres y formatos de campos, códigos de error y respuestas de escritura difieren (§1).
- **Hora:** `FEC_HORA` es la hora local **+ 4 h**; no es hora local (como dice el manual) ni UTC. Verificado contra la interfaz del hospital (§1.1).
- **Paginación no documentada**: páginas de 50 citas encadenadas por un token. Sin recorrerlas, el 07-10 se habrían entregado 50 de 111 citas (§1.2).
- **Errores "silenciosos"**: errores de negocio con HTTP 200, y varias peticiones mal formadas responden "OK, 0 citas" (§1).
- **Escrituras**: responden en texto plano, tardan entre 0.02 y 25 s y pueden aplicarse después de un timeout. Por eso el cliente **nunca reintenta** un `confirmar`/`anular` (§1.4).
- **Datos sucios**: el 90 % de los RUT con dígito verificador inválido, estados y especialidades fuera de catálogo (§2).
- **Abierto:** significado de los estados `5`/`9` y de los errores `ERR-07`/`ERR-09`, si anular notifica al paciente, y el desfase horario en invierno (§6, §7).

---

## 1. Diferencias entre el manual y el sistema real

| # | Tema | Manual | Sistema real | Impacto |
|---|---|---|---|---|
| 1 | Autenticación | `Authorization: Bearer <key>` | Cabecera `X-Auth-Token: <key>` | Sin esto no hay conexión |
| 2 | Códigos HTTP de error | 400 / 401 / 500 | Errores de negocio con **HTTP 200** y `{"estado":"ERROR","codigo":...,"msg":...}` | 🔴 Hay que leer el cuerpo, no solo el HTTP |
| 3 | Credencial expirada | 401 | **403** `ERR-01 "credencial expirada"`. Key inválida: 401 `"credencial no reconocida"` | El mismo `ERR-01` cubre casos distintos |
| 4 | Códigos de error | `ERR-01`, `ERR-02` | Además **`ERR-03 "token de continuacion invalido"`**, **`ERR-04 "no existe"`**, y en escrituras **`ERR-07`** (confirmar una confirmada) y **`ERR-09`** (confirmar una cancelada) | Hay códigos no documentados |
| 5 | Errores de infraestructura | — | **502 Bad Gateway intermitentes**, en HTML de nginx (no JSON). Al reintentar, la misma petición responde bien | 🟠 Hacen falta reintentos en las lecturas |
| 6 | Ruta inexistente | — | 404 `{"detail":"Not Found"}`, un tercer formato de error | — |
| 7 | `centro_id` | Opcional (centro por defecto según la key) | **Obligatorio**: sin él, `ERR-02 "parametros insuficientes"`. El **centro 3 es el Hospital** (Informática) y el único con datos (se probaron 0, -1 y del 1 al 100). **Un centro inexistente responde `OK` con 0 citas.** No hay endpoint de catálogo (`/centros` → 404) | 🟠 Un `centro_id` equivocado da una agenda vacía silenciosa |
| 8 | Validación de parámetros | — | `centro_id=abc` → **HTTP 422** con el formato de validación de FastAPI (`{"detail":[...]}`), un cuarto formato de error. `centro_id=3.0` se acepta como 3 | — |
| 9 | `fecha` | `YYYY-MM-DD HH:MM:SS` | Sin la parte de hora (`2026-10-28`) devuelve **`OK` con 0 citas, sin error**. La hora se ignora (`00:00:00` y `12:00:00` dan lo mismo) | 🔴 Agenda vacía falsa |
| 10 | **Zona horaria** | Hora local, sin zona | **`FEC_HORA` = hora local + 4 h** (§1.1). No es hora local, ni UTC real (en diciembre Chile está en UTC-3) | 🔴 Hora equivocada al paciente y citas en el día equivocado |
| 11 | Forma de la respuesta | Lista JSON | `{"estado":"OK","total":N,"citas":[...],"siguiente"?}`. Detalle: `{"estado":"OK","cita":{...}}` | — |
| 12 | Nombres de campos | `id, rut, nombre, fechaHora, estado, especialidad, profesional, telefono, email` | `ID_CITA, RUT_PAC, NOM_PAC, FEC_HORA, COD_EST, COD_PRO, NOM_PRO, MEDICO, CENTRO, TEL_PAC, OBS` | Todos distintos |
| 13 | Id de cita | Entero (`10432`) | Texto (`"AGD-0000010168"`). `/citas/10168` responde `ERR-04` | — |
| 14 | Estado | Texto: `AGENDADA` / `CONFIRMADA` / `CANCELADA` | **Número** `COD_EST`: **`1 = AGENDADA`** (contrastado con la interfaz), **`2 = CONFIRMADA`** y **`3 = CANCELADA`** (observados al escribir, §1.4). El 08-10 aparecen además **`5`** y **`9`**, de significado desconocido | 🟠 Hay estados sin catalogar |
| 15 | Filtro `estado` | Filtra por estado | **Se ignora**: `estado=CONFIRMADA` devuelve citas con `COD_EST=1` | 🟠 Hay que filtrar del lado del cliente |
| 16 | Paginación | v1.4: "se incorpora paginación (ver Anexo B)" | **El Anexo B no existe.** Páginas de **50 citas**, encadenadas por el token **`siguiente`** → parámetro **`desde`**. **`total` es la cantidad de la página, no del día** (§1.2) | 🔴 Sin recorrer las páginas se pierden citas |
| 17 | Especialidad | Nombre (`"Traumatología"`). Anexo A con 5 códigos | Código (`COD_PRO`) y nombre en mayúsculas sin tildes (`NOM_PRO`). Aparecen **`URGE`** (Urgencia Ambulatoria) y **`VACU`** (vacunación), fuera del catálogo | — |
| 18 | `email` | Existe (puede venir `null`) | **No existe.** Aparece `OBS` | No hay canal alternativo al teléfono |
| 19 | `OBS` | — | **Siempre `null` en la API**, aunque en la interfaz 3 citas tienen la observación "RESERVA INFORMATICA · PRUEBA INTEGRACION" | 🟠 Las citas de prueba no se pueden identificar por API |
| 20 | Formatos | ISO `2026-10-06T08:00:00`, RUT sin puntos, teléfono `+569XXXXXXXX`, nombre "Nombres Apellidos" | Fecha con espacio, RUT con puntos, teléfono con espacios (`+56 9 XXXX XXXX`), nombre `"APELLIDOS, NOMBRES"` en mayúsculas | Hay que normalizar |
| 21 | Ambiente QA | "En revisión" | No existe. Informática reservó **3 citas de prueba en producción** (15-12-2026); "el resto de la agenda no se debe modificar" (§3.2) | Escritura solo sobre esas 3 |
| 22 | Versión del manual | v1.4 (04-2021) | El documento tiene fecha 14-08-2019 (la de la v1.3) y "Revisado por: (pendiente)". Los cambios de la v1.4 (paginación, fechas) no están descritos | Todo el manual es sospechoso |
| 23 | Respuesta de `confirmar` / `anular` | No documentada | **Texto plano, no JSON**, siempre con **HTTP 200**: `OK` si se acepta, `ERR-xx` si se rechaza. **Inconsistente**: confirmar una confirmada da `ERR-07`, pero anular una cancelada da `OK` | 🔴 Un cliente que espera JSON informa error en una escritura exitosa |
| 24 | Latencia de las escrituras | — | **Muy variable: de 0.02 s a 25 s.** Una confirmación no respondió en 10 s y se aplicó entre 10 y 27 s después de enviarla; la relectura inmediata aún mostraba la cita agendada (§1.4) | 🔴 Un reintento automático habría confirmado dos veces |

### 1.1 Evidencia del desfase horario de +4 h

La interfaz de SIGAH indica explícitamente "Horas en hora local del establecimiento". Comparación de la misma agenda:

| | Interfaz (hora local) | API (`FEC_HORA`) |
|---|---|---|
| 15-12-2026, Medicina Interna, 20 citas | 08:00 → 17:30, cada 30 min | 12:00 → 21:30, cada 30 min |

- Desfase: **+4 h**. En diciembre Chile continental está en **UTC-3** (horario de verano), así que UTC real daría +3 h.
- Hipótesis: el servidor convierte a "UTC" con un **desfase fijo de -4 h** (hora estándar de Chile) e ignora el horario de verano. Sería consistente con los "ajustes en el manejo de fechas" de la v1.4 y con la migración a la nube (la API corre en Google Cloud Run, cuyos servidores usan UTC).
- Coincide con octubre: la API entrega 12:00–22:00 más 00:30, que en local es **08:00–18:00 más una urgencia a las 20:30 del día anterior**. Por eso SIGAH tiene 111 citas en su "día 07-10" y el día local 07-10 tiene 110: una cae el 06-10 a las 20:30.
- **No se puede verificar el comportamiento en invierno (abril–septiembre)**: no hay datos en ese período.
- *Corrección:* en un borrador inicial supusimos UTC-3 a partir del horario. La captura de la interfaz lo desmiente.

### 1.2 Paginación

Exploración antes de encontrar una respuesta paginada (sin documentación, con días de 20 citas o menos):

| Valor de `desde` | Respuesta |
|---|---|
| vacío | Igual que sin el parámetro |
| `0`, `5`, `99010`, base64 (`MTA=`, `{"offset":10}`) | `ERR-03 "token de continuacion invalido"` |
| `AGD-0000000000` | Todas las citas (como sin token) |
| `AGD-0000099001`, `AGD-0000099010` (ids reales del día) | **`OK` con `total: 0`**: agenda vacía silenciosa |

Unos 20 nombres de parámetros de tamaño de página o de rango de fechas (`page`, `limit`, `offset`, `hasta`…) se ignoran.

**Resuelto el 30-10.** Informática indicó que en octubre hubo más pacientes; al recorrer el mes, el **07-10** trajo la clave `siguiente`:

| Página | Citas | `siguiente` |
|---|---|---|
| 1 | 50 | token de 16 caracteres, forma `AAA-99999999-999` |
| 2 | 50 | otro token |
| 3 | 11 | no viene: última página |

- La primera página se pide **sin** `desde`; las siguientes, con `desde=<siguiente de la respuesta anterior>`.
- 111 citas, ninguna repetida entre páginas. El mismo token devuelve siempre la misma página, así que reintentar una página es seguro.
- **`total` es la cantidad de la página** (50, 50, 11): no sirve para detectar páginas faltantes.
- El cliente **solo usa tokens recibidos**, nunca los construye: uno inventado puede responder "OK, 0 citas". La forma del token explica por qué `AGD-0000099010` pasaba la validación.

### 1.3 La agenda de la captura corresponde al centro 3

La captura dice "Consultorio Adosado" e Informática dice que el centro 3 es "el Hospital". Para verificar que se trata de la misma agenda se comparó la estructura, sin exponer datos:

- **Diferencias entre RUT consecutivos** (ordenados por hora): en la captura, 18 saltos de 1 y uno final de 10. En la API, centro 3, 15-12: **idénticas**. Lo mismo ocurre con los teléfonos.
- Un solo profesional, Medicina Interna y 20 citas en ambos casos.
- Las filas reservadas para pruebas (13, 14 y 15 en la captura) corresponden a las posiciones 13, 14 y 15 de la API, a las 18:00, 18:30 y 19:00, en línea con el desfase de +4 h.
- Lectura probable: el *Consultorio Adosado de Especialidades* es la unidad ambulatoria del Hospital y comparte el centro 3.

### 1.4 Pruebas de escritura

Solo sobre las citas reservadas por Informática (§3.2). Antes de cada escritura se releyó la cita para verificar fecha, hora, especialidad y centro. Los cuerpos de texto plano de las primeras pruebas se identificaron comparando el SHA-256 guardado en la auditoría con candidatos (`OK`, `ERR-00`…`ERR-99`).

| Paso | Fecha | Cita (estado previo) | Acción | Resultado |
|---|---|---|---|---|
| A1 | 29-10 | 099013 (agendada) | `confirmar` (cliente, timeout 10 s) | Timeout sin respuesta; el cliente informó **resultado incierto** y no reintentó. Relectura inmediata: `COD_EST=1`; ~17 s después: `COD_EST=2` |
| A2 | 29-10 | 099013 (confirmada) | `confirmar` otra vez (POST directo) | `ERR-07` al instante. Estado sin cambios |
| B1 | 29-10 | 099014 (agendada) | `anular` (cliente) | `OK` en 20 ms, `COD_EST=3`. El cliente lo informó como error por no ser JSON: **corregido** |
| B2 | 29-10 | 099014 (cancelada) | `confirmar` (POST directo) | `ERR-09`. Estado sin cambios: SIGAH valida transiciones |
| B3 | 29-10 | 099013 (confirmada) | `anular` (cliente corregido) | `OK` **tras 25 s**, `COD_EST=3`. Con el timeout original de 10 s habría sido "incierto" |
| C1 | 31-10 | 099013 (**agendada**: restablecida por Informática) | `anular` (POST directo) | `OK`, `COD_EST=3`. Se esperaba la cita cancelada; ver nota |
| C2 | 31-10 | 099013 (cancelada) | `anular` otra vez (POST directo) | **`OK`**, estado sin cambios. A diferencia de confirmar, anular repetido no da error |

- **Las citas de prueba se restablecen**: entre el 30-10 y el 31-10, sin escrituras nuestras (según la auditoría), 099013 y 099014 volvieron a estar agendadas.
- *Nota sobre C1:* la verificación previa revisaba fecha, hora, especialidad y centro, pero no el estado. Desde entonces el script de pruebas también exige el estado esperado.
- 099015 nunca se usó. Las otras 17 citas del 15-12 siguieron agendadas durante todas las pruebas.

---

## 2. Calidad de datos observada

Días con datos: **05 al 08-10-2026**, **26 al 31-10-2026** y **15-12-2026**. Ningún otro día de octubre, ni los consultados de noviembre y diciembre, tiene citas.

| Verificación | Resultado |
|---|---|
| `ID_CITA` únicos | ✅ Sin repetidos, tampoco entre páginas |
| Dígito verificador del RUT válido (muestra 26–31-10) | **6/60**. En la interfaz todos los RUT terminan en `-5`: es un problema de origen |
| Pacientes distintos (26–31-10) | **20**, cada uno con 3 citas en la semana y nunca dos el mismo día |
| **Vacunación del 07-10** | Las 110 citas del día local son de `VACU`: **20 pacientes con 5 o 6 citas cada uno**, siempre con el mismo profesional, repartidas en 7 a 10 horas. ¿Bloques reservados o datos de prueba? (§6) |
| Estados fuera de catálogo | `COD_EST` 5 (×2) y 9 (×1) el 08-10 |
| Médico con dos citas a la misma hora | 0 |
| Teléfono con formato de móvil chileno | 100 % |
| `COD_PRO` ↔ `NOM_PRO` consistentes | ✅ |
| Lista vs. detalle (`/citas/{id}`) | Mismos campos y valores |
| ¿Los GET modifican datos? | No en lo visible: el SHA-256 de 4 respuestas es idéntico antes y después de 12 consultas repetidas. Un efecto interno no expuesto (ej. "último acceso") no es verificable |
| API vs. interfaz (15-12) | Misma cantidad (20), especialidad, profesional y estado. Hora +4 h. `OBS` no aparece en la API |

---

## 3. Decisiones y supuestos

| Decisión | Por qué |
|---|---|
| **Modelo propio** (`Cita`, `Paciente`, `EstadoCita`) con un traductor desde los campos SIGAH | El resto de la plataforma no debe conocer `NOM_PAC` ni `COD_EST` |
| **Solo `ID_CITA` y `FEC_HORA` son imprescindibles.** Sin ellos la cita se descarta con un error en el log; el resto de la agenda sigue | Sin id no se puede confirmar ni anular; sin fecha no se sabe qué día es. Una cita rota no debe dejar sin llamada a las demás |
| **Cualquier otro dato ausente o inválido queda en `None`** (RUT con formato inválido, teléfono no interpretable…) y se registra un aviso en el log de calidad, sin valores personales. Un RUT con DV inválido se conserva | Descartar la cita dejaría a un paciente sin su llamada. `None` le dice a la plataforma qué falta |
| **Se valida el cuerpo, no solo el HTTP**: `estado != "OK"` o `ERR-xx` en texto plano → excepción tipada según el código | Los errores llegan con HTTP 200 |
| **Respuestas de escritura en texto plano**: `OK` es éxito | Así responden `confirmar` y `anular` (§1.4) |
| **Paginación: se sigue `siguiente` → `desde` hasta que no venga.** Si un token se repite o se superan 100 páginas → error | Agenda completa; el tope evita un bucle infinito si SIGAH falla |
| **Cualquier otra clave desconocida en la respuesta → error** | Un cambio de formato no documentado podría significar datos parciales. Así se detectó la paginación |
| **La fecha siempre se envía con hora** (`YYYY-MM-DD 00:00:00`) | Sin hora, SIGAH responde "OK, 0 citas" |
| **`FEC_HORA` se interpreta como hora local + 4 h** (configurable) y se expone con zona `America/Santiago` | Evidencia en §1.1. Configurable porque no conocemos el comportamiento en invierno |
| **Agenda por días locales**: se piden los días SIGAH necesarios (cada uno una sola vez, aunque lo compartan dos días locales) y se filtra por fecha local. Admite varios días (`--dias`, máximo 31, para que un error de tipeo no sature producción) | Las citas locales desde las 20:00 caen en el día SIGAH siguiente. El flujo pide "la agenda de los próximos días" |
| **`COD_EST`: `1 → AGENDADA`, `2 → CONFIRMADA`, `3 → CANCELADA`. Cualquier otro valor → `DESCONOCIDO`**, nunca se adivina | 1 contrastado con la interfaz; 2 y 3 observados en las pruebas de escritura |
| **El filtro por estado se aplica en el cliente** | El servidor lo ignora |
| **Reintentos solo en lecturas** (red caída, timeout, HTTP 5xx), con espera exponencial (1, 2, 4 s) | Los 502 son intermitentes y leer es seguro de repetir |
| **HTTP 429 en lecturas: se reintenta esperando lo que pida `Retry-After`** (en segundos, con tope de 60 s; si no viene, la espera normal) | No se observó, pero SIGAH corre en Google Cloud Run, que responde 429 cuando se queda sin instancias disponibles |
| **Las escrituras nunca se reintentan.** Ante timeout o 5xx se relee la cita y se informa "resultado incierto". Ante 429 se informa que **no se aplicó** | Una confirmación se aplicó después de su timeout (A1), y no se sabe si anular notifica al paciente cada vez. Un 429, en cambio, indica que la petición se rechazó sin procesarse |
| **Antes de confirmar o anular se relee la cita** y se exige un estado compatible (confirmar: agendada; anular: agendada o confirmada) | El estado puede cambiar entre la descarga de la mañana y la llamada. Evita también anular dos veces |
| **Timeout de escritura propio (60 s)**, separado del de lectura (10 s) | Las escrituras tardaron hasta 25 s |
| **Normalización**: RUT sin puntos con DV en mayúscula, teléfono en E.164, nombre separado en apellidos y nombres, centro como número | Datos con formatos distintos al manual |
| **Centro 3 (Hospital) por defecto**, configurable | Confirmado por Informática y único con datos. Un centro equivocado responde "OK, 0 citas" sin error |
| **Solo la API key es obligatoria**: URL, centro, desfase, timeouts y horarios tienen valores por defecto, como constantes con nombre y motivo | Requisito: clonar, configurar la key y obtener la agenda |
| **Auditoría en SQLite, tres tablas.** `auditoria`: cada llamada a SIGAH (URL, HTTP, `x-cloud-trace-context`, cuerpo, y en escrituras la intención antes de enviar). `salidas`: lo que el cliente **entrega** a la plataforma (nuestra interpretación) o el error que informa. `eventos`: problemas de calidad y alertas de reglas, **una fila por cita y con código estable** (`ProblemaCalidad` / `TipoAlerta`). Todo con datos personales enmascarados (lista blanca de campos) y el SHA-256 del original | Evidencia de lo que SIGAH dijo **y de lo que nosotros dijimos**, consultable por código, sin guardar una copia de los datos de pacientes |
| **Escritura doblemente protegida**: la librería la trae deshabilitada y el CLI solo escribe sobre ids listados en `SIGAH_IDS_ESCRIBIBLES` | En producción solo las citas de prueba deben poder modificarse |
| **Reglas de negocio separadas del cliente** (`reglas.revisar`): devuelven alertas sin modificar ni descartar citas | La plataforma decide qué hacer con cada alerta |
| **Sin base de datos de agenda ni tareas programadas** | El alcance es el cliente; programar la ejecución y guardar la agenda le corresponde a la plataforma |

### 3.1 Reglas de negocio (alertas)

| Alerta | Cuándo |
|---|---|
| `paciente_misma_hora` | Mismo RUT, mismo inicio |
| `paciente_misma_especialidad_dia` | Mismo RUT, misma especialidad, mismo día |
| `sin_contacto` | Sin teléfono válido (el único canal de contacto) |
| `estado_desconocido` | `COD_EST` no catalogado |
| `horario_fuera_de_rango` | Inicio fuera de 07:00–21:00 (configurable). También avisa si el desfase horario cambia |
| `cita_pasada` | Inicio anterior al momento de la revisión |
| `profesional_misma_hora` | **Opcional, apagada por defecto.** Mismo profesional, mismo inicio; excluye equipos ("EQUIPO …") |

Limitaciones:
- SIGAH no informa la **duración** de las citas: solo se detectan inicios idénticos, no solapamientos.
- El profesional viene **solo como nombre abreviado** ("DRA. ROJAS I."), sin id: dos médicos homónimos generarían falsos positivos. Por eso esa regla es opcional.
- Los pacientes se identifican por RUT. Una cita sin RUT válido no participa en las reglas de paciente.

### 3.2 Citas de prueba para escritura

Según la interfaz, Informática reservó 3 citas el 15-12-2026 (Medicina Interna, centro 3), a las **14:00, 14:30 y 15:00 hora local**:

| Hora local | `FEC_HORA` API | `ID_CITA` | Estado al 31-10 |
|---|---|---|---|
| 14:00 | 18:00 | `AGD-0000099013` | cancelada |
| 14:30 | 18:30 | `AGD-0000099014` | agendada (restablecida) |
| 15:00 | 19:00 | `AGD-0000099015` | agendada (nunca usada) |

- La asociación coincide por **dos vías independientes**: el desfase horario (§1.1) y la posición de los pacientes en la secuencia (§1.3). La API no expone la observación que las marca.
- **Informática confirmó los tres ids el 30-10**, después de las primeras pruebas, que se hicieron con la evidencia anterior.
- Informática **restablece** estas citas (§1.4), así que se pueden reutilizar.

---

## 4. Comunicación con Informática

Las consultas se agruparon y priorizaron para no ocupar más tiempo del necesario. Lo que se podía verificar con evidencia se verificó antes de preguntar.

| Fecha | Consulta | Respuesta | Qué se decidió |
|---|---|---|---|
| 27-10 | La API key entregada está expirada (403). Pedido de una nueva y de un ambiente o datos de prueba para escritura | Nueva key (28-10) | Trabajo en **solo lectura** hasta resolver la escritura |
| 28-10 | Seguimiento: escribir en producción es inviable sin datos de prueba | Sin respuesta ese día | Se mantiene solo lectura |
| 29-10 | Consultas priorizadas: centros, paginación, estados, códigos de error, respuestas de escritura, datos de prueba | "El centro 3 es el Hospital", "la API tiene paginación" y una **captura de la interfaz** con 3 citas reservadas para pruebas | La captura permitió verificar el desfase (§1.1), el centro (§1.3) e identificar las citas de prueba (§3.2). Se probó la escritura sobre ellas (§1.4) |
| 29-10 | Confirmar los ids de prueba; en qué campo viene el token de paginación | (30-10) "Correcto", y que en octubre hubo más pacientes | Ids confirmados. La paginación se encontró recorriendo octubre (§1.2), sin esperar más detalles |
| — | Sin respuesta: estados 5 y 9, errores `ERR-07`/`ERR-09`, notificaciones al anular, catálogo de especialidades, vacunación del 07-10, `OBS` | — | Se documentan como preguntas abiertas (§6). El cliente se protege igual: estados desconocidos sin adivinar, escrituras sin reintento |

El desfase horario **no se preguntó**: la captura de la interfaz lo demuestra (§1.1).

---

## 5. Riesgos antes de producción

1. **Desfase horario en invierno.** El +4 h está verificado en octubre y diciembre (horario de verano). Si en invierno SIGAH cambia de comportamiento, se le informaría al paciente una hora equivocada. La alerta `horario_fuera_de_rango` lo delataría (citas de madrugada).
2. **Estados incompletos.** Conocemos 1, 2 y 3; existen al menos 5 y 9. Una cita en estado desconocido no se debe llamar ni modificar sin revisión.
3. **Paginación verificada en un solo día** (07-10, 3 páginas). Como `total` no detecta páginas faltantes, la completitud depende de que SIGAH entregue `siguiente` de forma consistente.
4. **Escrituras lentas o diferidas.** Si `confirmar`/`anular` supera el timeout, el resultado es incierto y una relectura inmediata puede no reflejarlo. La plataforma debe revisar esos casos más tarde (la auditoría los registra), nunca reintentarlos a ciegas.
5. **Notificaciones al anular.** Según el manual, anular notifica al paciente. No sabemos si anular una cita ya cancelada (que responde `OK`) vuelve a notificar.
6. **Inestabilidad.** Hay 502 intermitentes. Si coinciden con una escritura, el resultado es incierto.
7. **Agendas vacías silenciosas.** Un centro, una fecha o un token incorrectos responden "OK, 0 citas". Conviene que la plataforma alerte cuando un día hábil viene vacío.
8. **Datos personales y de salud.** La auditoría y los logs no guardan datos de pacientes en claro; cualquier almacenamiento nuevo debe mantenerlo (Ley 19.628 / Ley 21.719).
9. **Solo hay canal telefónico.** No hay email: una cita sin teléfono válido no tiene forma de contacto (alerta `sin_contacto`).
10. **Manual no confiable y cambios del proveedor.** Ante una clave nueva en la respuesta, el cliente falla explícitamente en vez de entregar datos parciales; ante un campo de la cita ausente o con otro formato, lo deja en `None` y lo registra.

---

## 6. Preguntas abiertas

| # | Pregunta | Estado |
|---|---|---|
| 1 | ¿Qué significan los estados `COD_EST` 5 y 9? ¿Hay otros? | Pendiente. 1, 2 y 3 resueltos (§1.4) |
| 2 | ¿Qué significan `ERR-07` y `ERR-09`? ¿Hay una lista completa de códigos? | Pendiente. Comportamiento observado en §1.4 |
| 3 | ¿Anular envía una notificación al paciente? ¿También si la cita ya estaba cancelada? | Pendiente |
| 4 | ¿Por qué las escrituras tardan hasta 25 s? ¿Se procesan de forma asíncrona? | Pendiente |
| 5 | ¿El desfase de +4 h se mantiene en invierno? | Pendiente (no hay datos de abril–septiembre) |
| 6 | ¿Qué otros centros existen y cuáles nos corresponden? | Parcial: centro 3 = Hospital, único con datos |
| 7 | Catálogo completo de especialidades (`URGE` y `VACU` no están en el Anexo A) | Pendiente |
| 8 | 07-10: ¿20 pacientes con 5 o 6 citas de vacunación cada uno es real? | Pendiente |
| 9 | ¿Los datos son reales? 90 % de RUT con DV inválido, pacientes repetidos, citas en solo 11 días | Pendiente |
| 10 | `OBS` sale `null` en la API aunque en la interfaz tiene contenido. ¿Es otro campo? | Pendiente |
| 11 | ¿Quién restablece las citas de prueba y cada cuánto? | Pendiente (observado en §1.4) |
| — | Resueltas: paginación (§1.2), ids de las citas de prueba (§3.2), centro del Hospital (§1.3), respuestas y transiciones de escritura (§1.4), vigencia de la key | ✅ |

---

## 7. Cómo se verificó

- **Lecturas:** unas 250 en total. Las primeras, exploratorias, con un script de sondeo que enmascaraba los datos personales; las 81 posteriores, con el propio cliente y registradas en su auditoría.
- **Escrituras:** 7, solo sobre 2 de las 3 citas reservadas para pruebas (§1.4), todas auditadas.
- **Fechas:** todo octubre 2026, varias de noviembre y diciembre (incluido el 15-12). Centros 0, -1 y del 1 al 100.
- **Rutas:** `/citas` (variantes de `fecha`, `centro_id`, `estado` y unos 20 parámetros de paginación), `/citas/{id}` (válido, inexistente y numérico), `/citas/{id}/confirmar` y `/anular` (§1.4), y rutas de documentación (`/docs`, `/openapi.json`), que no existen.
- **Contraste** con la captura de la interfaz de SIGAH 4.2 (agenda del 15-12-2026) enviada por Informática.
- **Tests automáticos:** 57, contra un SIGAH simulado con los comportamientos observados y datos inventados.
