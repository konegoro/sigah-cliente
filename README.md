# sigah-cliente

Cliente Python de la API de agenda **SIGAH** (Hospital Regional de Puerto Aldea): consultar citas por fecha o por id, confirmarlas y anularlas, expuestas en un modelo de datos propio.

El sistema real difiere bastante de su manual (autenticación, nombres de campos, zona horaria, errores, paginación). Las diferencias, los supuestos y las preguntas abiertas están en **[HALLAZGOS.md](HALLAZGOS.md)**.

## Instalación

Requiere Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Configuración

```bash
cp .env.example .env               # y completar SIGAH_API_KEY
```

| Variable | Por defecto | Descripción |
|---|---|---|
| `SIGAH_API_KEY` | — | **Obligatoria.** Se envía en la cabecera `X-Auth-Token` |
| `SIGAH_IDS_ESCRIBIBLES` | vacío | Ids que se pueden confirmar/anular, separados por coma. Vacío = escritura bloqueada |
| `SIGAH_CENTRO_ID` | `3` | Centro (3 = Hospital) |
| `SIGAH_URL_BASE` | ambiente entregado | URL base de la API |
| `SIGAH_DESFASE_HORAS` | `4` | Horas que SIGAH suma a la hora local ([HALLAZGOS §1.1](HALLAZGOS.md#11-evidencia-del-desfase-horario-de-4-h)) |
| `SIGAH_AUDITORIA` | `sigah_auditoria.db` | Archivo SQLite de auditoría |
| `SIGAH_HORA_MIN` / `SIGAH_HORA_MAX` | `07:00` / `21:00` | Rango horario plausible (regla `horario_fuera_de_rango`) |
| `SIGAH_REVISAR_PROFESIONAL` | `0` | `1` activa la regla de profesional con dos citas a la misma hora |

> ⚠️ El ambiente entregado es **producción**: confirmar o anular afecta a pacientes reales.

## Uso: CLI

```bash
sigah agenda 2026-12-15            # citas del día (hora de Chile) + alertas
sigah cita AGD-0000099013
sigah confirmar AGD-0000099013     # solo si el id está en SIGAH_IDS_ESCRIBIBLES
sigah anular AGD-0000099013
```

RUT, nombre y teléfono se muestran enmascarados (`***`); `--completo` los muestra.

```
AGD-0000099013  2026-12-15 14:00  agendada    MINT  DRA. ROJAS I.      ***  ***  ***
```

## Uso: librería

```python
from datetime import date
from sigah import Auditoria, SigahClient, revisar

with Auditoria() as auditoria, SigahClient(api_key, centro_id=3, auditoria=auditoria) as cliente:
    citas = cliente.agenda(date(2026, 12, 15))   # list[Cita], día local completo
    for alerta in revisar(citas):
        print(alerta.tipo, alerta.cita_ids)

    cita = cliente.cita("AGD-0000099013")
    print(cita.inicio, cita.estado, cita.paciente.telefono)
```

La escritura (`confirmar`, `anular`) requiere `SigahClient(..., permitir_escritura=True)`.

| Error | Cuándo |
|---|---|
| `AutenticacionError` | API key ausente, inválida o expirada |
| `SolicitudInvalidaError` | Parámetros rechazados |
| `CitaNoEncontradaError` | El id no existe |
| `RespuestaInesperadaError` | Formato que no se puede interpretar con seguridad (ej. paginación no soportada) |
| `ServicioNoDisponibleError` | SIGAH no responde tras los reintentos |
| `EscrituraNoPermitidaError` | Escritura deshabilitada o estado actual incompatible |
| `ResultadoInciertoError` | Se envió una escritura y no se sabe si se aplicó: **revisar antes de reintentar** |

Todos heredan de `SigahError`.

## Comportamiento

- **Día local:** `agenda(fecha)` entrega las citas de 00:00 a 23:59 hora de Chile, consultando los días de SIGAH necesarios por el desfase.
- **Reintentos:** las lecturas se reintentan ante fallas de red o HTTP 5xx, con espera exponencial. Las escrituras **nunca** se reintentan.
- **Antes de escribir** se relee la cita y se valida su estado.
- **Datos sucios:** solo `id` e `inicio` son imprescindibles; cualquier otro dato inválido queda en `None` y se registra en el logger `sigah.calidad`, sin datos personales.
- **Auditoría:** cada llamada HTTP queda en SQLite con su cuerpo enmascarado, el SHA-256 del original y el `x-cloud-trace-context` de SIGAH.
- **Reglas de negocio:** `revisar(citas)` devuelve alertas (tope horario, sin contacto, estado desconocido, etc.) sin modificar las citas. Detalle en [HALLAZGOS §3.1](HALLAZGOS.md#31-reglas-de-negocio-alertas).

## Tests

```bash
pytest
```

Contra un SIGAH simulado (respx) con datos inventados; no usan la red.

## Estructura

```
sigah/
  modelos.py     Cita, Paciente, EstadoCita
  mapeo.py       registro SIGAH → Cita (fechas, RUT, teléfono, estado)
  cliente.py     SigahClient: HTTP, reintentos, validación
  errores.py     excepciones
  auditoria.py   registro SQLite enmascarado
  reglas.py      alertas de negocio
  cli.py         comando `sigah`
tests/
```
