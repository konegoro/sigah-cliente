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
    """Reemplaza dígitos por 9 y letras por X fuera de CAMPOS_SEGUROS, conservando la forma."""
    if isinstance(valor, dict):
        return {k: enmascarar(v, seguro and k in CAMPOS_SEGUROS) for k, v in valor.items()}
    if isinstance(valor, list):
        return [enmascarar(v, seguro) for v in valor]
    if seguro or valor is None or isinstance(valor, bool):
        return valor
    return re.sub(r"[^\W\d_]", "X", re.sub(r"\d", "9", str(valor)))
