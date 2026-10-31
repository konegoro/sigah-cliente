"""Traducción de registros SIGAH al modelo propio.

Solo `ID_CITA` y `FEC_HORA` son imprescindibles. Cualquier otro dato ausente o inválido
queda en `None` y se registra en el logger `sigah.calidad` (sin datos personales).
"""
import logging
import re
from datetime import date, datetime, time, timedelta

from .modelos import ZONA, Cita, EstadoCita, Paciente

# 1: confirmado contra la interfaz de SIGAH. 2 y 3: observados al confirmar y anular citas de prueba.
ESTADOS = {1: EstadoCita.AGENDADA, 2: EstadoCita.CONFIRMADA, 3: EstadoCita.CANCELADA}

log = logging.getLogger("sigah.calidad")


def dias_sigah(fecha: date, desfase_horas: int) -> list[date]:
    """Días que hay que pedir a SIGAH para cubrir el día local `fecha` (con +4 h: ese día y el siguiente)."""
    inicio = datetime.combine(fecha, time()) + timedelta(hours=desfase_horas)
    fin = inicio + timedelta(days=1) - timedelta(seconds=1)
    return sorted({inicio.date(), fin.date()})


def citas_del_dia(registros: list[dict], fecha: date, desfase_horas: int) -> list[Cita]:
    """Mapea solo los registros cuyo inicio cae en el día local `fecha`."""
    citas = []
    for reg in registros:
        inicio = _inicio(reg.get("FEC_HORA"), desfase_horas)
        if inicio is not None and inicio.date() != fecha:
            continue  # pertenece a otro día local
        cita = a_cita(reg, desfase_horas)
        if cita is not None:
            citas.append(cita)
    return citas


def a_cita(reg: dict, desfase_horas: int) -> Cita | None:
    """Convierte un registro SIGAH en `Cita`, o `None` si le falta id o fecha válida."""
    id_ = _texto(reg.get("ID_CITA"))
    inicio = _inicio(reg.get("FEC_HORA"), desfase_horas)
    if id_ is None or inicio is None:
        log.error("Cita descartada (id=%s): falta id o FEC_HORA válida", id_ or "?")
        return None

    apellidos, nombres = _nombre(id_, reg.get("NOM_PAC"))
    return Cita(
        id=id_,
        inicio=inicio,
        estado=_estado(id_, reg.get("COD_EST")),
        paciente=Paciente(
            rut=_rut(id_, reg.get("RUT_PAC")),
            nombres=nombres,
            apellidos=apellidos,
            telefono=_telefono(id_, reg.get("TEL_PAC")),
        ),
        especialidad=_texto(reg.get("COD_PRO")),
        especialidad_nombre=_texto(reg.get("NOM_PRO")),
        profesional=_texto(reg.get("MEDICO")),
        centro_id=_centro(id_, reg.get("CENTRO")),
    )


def _texto(valor) -> str | None:
    return (valor.strip() or None) if isinstance(valor, str) else None


def _inicio(valor, desfase_horas: int) -> datetime | None:
    """SIGAH entrega la hora local + `desfase_horas`, sin zona (ver HALLAZGOS §1.1)."""
    try:
        bruto = datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return None
    return (bruto - timedelta(hours=desfase_horas)).replace(tzinfo=ZONA)


def _estado(id_: str, valor) -> EstadoCita:
    estado = ESTADOS.get(valor) if isinstance(valor, int) else None
    if estado is None:
        log.warning("%s: COD_EST desconocido (%r)", id_, valor)
        return EstadoCita.DESCONOCIDO
    return estado


def _centro(id_: str, valor) -> int | None:
    """Acepta 3 o "3"; cualquier otro valor queda en None."""
    if isinstance(valor, int) and not isinstance(valor, bool):  # bool es subclase de int: True no es un centro
        return valor
    if isinstance(valor, str) and valor.strip().isdecimal():
        return int(valor)
    log.warning("%s: CENTRO ausente o no interpretable", id_)
    return None


def _rut(id_: str, valor) -> str | None:
    texto = (_texto(valor) or "").replace(".", "").replace(" ", "").upper()
    m = re.fullmatch(r"(\d{7,8})-?([\dK])", texto)
    if not m:
        log.warning("%s: RUT ausente o con formato inválido", id_)
        return None
    cuerpo, dv = m.groups()
    if dv != _dv(cuerpo):
        log.warning("%s: RUT con dígito verificador inválido", id_)
    return f"{cuerpo}-{dv}"


def _dv(cuerpo: str) -> str:
    suma = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(cuerpo)))
    resto = 11 - suma % 11
    return {10: "K", 11: "0"}.get(resto, str(resto))


def _telefono(id_: str, valor) -> str | None:
    """Normaliza a E.164 (+56 y 9 dígitos)."""
    digitos = re.sub(r"\D", "", _texto(valor) or "")
    if len(digitos) == 11 and digitos.startswith("56"):
        digitos = digitos[2:]
    if len(digitos) != 9:
        log.warning("%s: teléfono ausente o no interpretable", id_)
        return None
    return f"+56{digitos}"


def _nombre(id_: str, valor) -> tuple[str | None, str | None]:
    """SIGAH entrega "APELLIDOS, NOMBRES"."""
    texto = _texto(valor)
    if texto is None:
        log.warning("%s: nombre de paciente ausente", id_)
        return None, None
    apellidos, coma, nombres = texto.partition(",")
    if not coma:
        log.warning("%s: nombre sin separador de apellidos", id_)
        return None, texto
    return _texto(apellidos), _texto(nombres)
