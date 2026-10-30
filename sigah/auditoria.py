"""Registro de auditoría de cada llamada HTTP en SQLite.

Guarda el cuerpo completo con los datos personales enmascarados, más el SHA-256 del
cuerpo original: permite probar qué se recibió sin conservar una copia de los datos.
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

# Lista blanca: todo campo fuera de ella se enmascara, incluidos los que SIGAH agregue en el futuro.
CAMPOS_SEGUROS = {
    "estado", "codigo", "msg", "total", "cita", "citas", "detail",
    "ID_CITA", "FEC_HORA", "COD_EST", "COD_PRO", "NOM_PRO", "MEDICO", "CENTRO",
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS auditoria (
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
)
"""


class Auditoria:
    def __init__(self, ruta: str = "sigah_auditoria.db"):
        self._db = sqlite3.connect(ruta)
        self._db.row_factory = sqlite3.Row
        self._db.execute(_ESQUEMA)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._db.close()

    def registrar(self, metodo: str, url: str, fase: str, *, http_status: int | None = None,
                  trace: str | None = None, cuerpo: str | None = None, error: str | None = None) -> None:
        sha = hashlib.sha256(cuerpo.encode()).hexdigest() if cuerpo is not None else None
        with self._db:  # commit por fila: el "intento" debe quedar escrito antes de enviar el POST
            self._db.execute(
                "INSERT INTO auditoria (fecha_utc, metodo, url, fase, http_status, trace, sha256, cuerpo, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), metodo, url, fase, http_status, trace,
                 sha, _enmascarar_cuerpo(cuerpo), error),
            )

    def registros(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM auditoria ORDER BY id")]


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
