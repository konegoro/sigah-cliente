"""Auditoría en SQLite: llamadas a SIGAH, lo que se entrega a la plataforma, y eventos de calidad y de reglas.

Los cuerpos se guardan con los datos personales enmascarados, más el SHA-256 del original:
permite probar qué se recibió o se entregó sin conservar una copia de los datos.
"""
import hashlib
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum

from .mapeo import log as log_calidad

# Lista blanca: todo campo fuera de ella se enmascara, incluidos los que SIGAH agregue en el futuro.
CAMPOS_SEGUROS = {
    # respuestas de SIGAH
    "estado", "codigo", "msg", "total", "cita", "citas", "siguiente", "detail",
    "ID_CITA", "FEC_HORA", "COD_EST", "COD_PRO", "NOM_PRO", "MEDICO", "CENTRO",
    # modelo propio (lo entregado a la plataforma); "paciente" no está: se enmascara completo
    "id", "inicio", "especialidad", "especialidad_nombre", "profesional", "centro_id",
}

TABLAS = ("auditoria", "salidas", "eventos")
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS auditoria (  -- cada llamada HTTP a SIGAH
    id INTEGER PRIMARY KEY,
    fecha_utc TEXT NOT NULL,
    metodo TEXT NOT NULL,
    url TEXT NOT NULL,
    fase TEXT NOT NULL,          -- intento | respuesta | error
    http_status INTEGER,
    trace TEXT,                  -- x-cloud-trace-context, para cruzar con los logs de SIGAH
    sha256 TEXT,                 -- del cuerpo original
    cuerpo TEXT,                 -- enmascarado
    error TEXT
);
CREATE TABLE IF NOT EXISTS salidas (  -- lo que el cliente entrega a la plataforma
    id INTEGER PRIMARY KEY,
    fecha_utc TEXT NOT NULL,
    operacion TEXT NOT NULL,     -- agenda | cita | confirmar | anular
    parametros TEXT NOT NULL,    -- JSON, ej. {"fecha": "2026-12-15", "dias": 1}
    cantidad INTEGER,            -- citas entregadas
    sha256 TEXT,                 -- del resultado original
    resultado TEXT,              -- JSON del modelo propio, enmascarado
    error TEXT                   -- si la operación falló: el error que se informó
);
CREATE TABLE IF NOT EXISTS eventos (  -- problemas de calidad de los datos y alertas de reglas
    id INTEGER PRIMARY KEY,
    fecha_utc TEXT NOT NULL,
    origen TEXT NOT NULL,        -- calidad | regla
    codigo TEXT NOT NULL,        -- ProblemaCalidad o TipoAlerta, ej. "rut_dv_invalido": consultar por este
    cita_id TEXT,                -- una fila por cita
    relacionadas TEXT,           -- en alertas de grupo: los ids de todo el grupo
    detalle TEXT                 -- legible y sin datos personales; puede cambiar, no consultar por él
);
"""


class Auditoria:
    def __init__(self, ruta: str = "sigah_auditoria.db"):
        self._db = sqlite3.connect(ruta)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_ESQUEMA)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._db.close()

    def registrar(self, metodo: str, url: str, fase: str, *, http_status: int | None = None,
                  trace: str | None = None, cuerpo: str | None = None, error: str | None = None) -> None:
        """Una llamada HTTP a SIGAH."""
        with self._db:  # commit por fila: el "intento" debe quedar escrito antes de enviar el POST
            self._db.execute(
                "INSERT INTO auditoria (fecha_utc, metodo, url, fase, http_status, trace, sha256, cuerpo, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_ahora(), metodo, url, fase, http_status, trace, _sha(cuerpo), _enmascarar_cuerpo(cuerpo), error),
            )

    def registrar_salida(self, operacion: str, parametros: dict, resultado=None, error: str | None = None) -> None:
        """Lo que se entregó a la plataforma: el resultado (una Cita o una lista de Citas) o el error informado."""
        cuerpo = None if resultado is None else _a_json(resultado)
        cantidad = None if resultado is None else (len(resultado) if isinstance(resultado, list) else 1)
        with self._db:
            self._db.execute(
                "INSERT INTO salidas (fecha_utc, operacion, parametros, cantidad, sha256, resultado, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_ahora(), operacion, json.dumps(parametros, default=str), cantidad, _sha(cuerpo),
                 _enmascarar_cuerpo(cuerpo), error),
            )

    def registrar_evento(self, origen: str, codigo: str, cita_id: str | None, detalle: str,
                         relacionadas: str | None = None) -> None:
        """Un problema de calidad o una alerta de regla. `detalle` no debe llevar datos personales."""
        with self._db:
            self._db.execute(
                "INSERT INTO eventos (fecha_utc, origen, codigo, cita_id, relacionadas, detalle)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (_ahora(), origen, codigo, cita_id, relacionadas, detalle),
            )

    def registrar_alertas(self, alertas) -> None:
        """Las alertas de `reglas.revisar`: una fila por cita involucrada."""
        for alerta in alertas:
            relacionadas = ",".join(alerta.cita_ids) if len(alerta.cita_ids) > 1 else None
            for cita_id in alerta.cita_ids:
                self.registrar_evento("regla", alerta.tipo.value, cita_id, alerta.detalle, relacionadas)

    @contextmanager
    def capturar_calidad(self):
        """Mientras dure el bloque, guarda en `eventos` cada aviso del log `sigah.calidad`."""
        handler = _HandlerCalidad(self)
        log_calidad.addHandler(handler)
        try:
            yield
        finally:
            log_calidad.removeHandler(handler)

    def registros(self, tabla: str = "auditoria") -> list[dict]:
        # Un nombre de tabla no puede ir como parámetro "?": se valida contra la lista antes de armar el SQL.
        if tabla not in TABLAS:
            raise ValueError(f"Tabla desconocida: {tabla!r}")
        return [dict(r) for r in self._db.execute(f"SELECT * FROM {tabla} ORDER BY id")]


class _HandlerCalidad(logging.Handler):
    """Lleva cada aviso del log `sigah.calidad` a la tabla `eventos`, con su código estable."""

    def __init__(self, auditoria: Auditoria):
        super().__init__(logging.WARNING)
        self._auditoria = auditoria

    def emit(self, record: logging.LogRecord) -> None:
        problema = getattr(record, "problema", None)
        self._auditoria.registrar_evento("calidad", problema.value if problema else "sin_codigo",
                                         getattr(record, "cita_id", None), record.getMessage())


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(texto: str | None) -> str | None:
    return hashlib.sha256(texto.encode()).hexdigest() if texto is not None else None


def _a_json(valor) -> str:
    """JSON de lo entregado (una Cita o una lista): fechas en ISO y enums por su valor."""
    def convertir(objeto):
        if isinstance(objeto, Enum):
            return objeto.value
        if isinstance(objeto, datetime):
            return objeto.isoformat()
        raise TypeError(f"No se puede convertir a JSON: {type(objeto).__name__}")

    datos = [asdict(v) for v in valor] if isinstance(valor, list) else asdict(valor)
    return json.dumps(datos, default=convertir, ensure_ascii=False)


def _enmascarar_cuerpo(cuerpo: str | None) -> str | None:
    if cuerpo is None:
        return None
    # Respuestas de escritura ("OK" o un código "ERR-xx"): no traen datos personales.
    if re.fullmatch(r"OK|ERR-\d+", cuerpo.strip()):
        return cuerpo
    try:
        return json.dumps(enmascarar(json.loads(cuerpo)), ensure_ascii=False)
    except ValueError:
        return enmascarar(cuerpo, seguro=False)


def enmascarar(valor, seguro: bool = True):
    """Enmascara todo valor que no esté bajo un campo de CAMPOS_SEGUROS, conservando su forma.

    Ej.: {"ID_CITA": "AGD-1", "RUT_PAC": "12.345.678-5"} → {"ID_CITA": "AGD-1", "RUT_PAC": "99.999.999-9"}
    """
    if isinstance(valor, dict):  # cada campo hereda "seguro" solo si su nombre está en la lista blanca
        return {campo: enmascarar(v, seguro and campo in CAMPOS_SEGUROS) for campo, v in valor.items()}
    if isinstance(valor, list):  # los elementos de una lista heredan lo que tenga la lista
        return [enmascarar(v, seguro) for v in valor]
    if seguro or valor is None or isinstance(valor, bool):
        return valor
    texto = re.sub(r"\d", "9", str(valor))  # dígitos → 9
    return re.sub(r"[^\W\d_]", "X", texto)  # letras (con tildes y ñ) → X
