"""Traducción de registros SIGAH al modelo propio.

Solo `ID_CITA` y `FEC_HORA` son imprescindibles. Cualquier otro dato ausente o inválido
queda en `None` y se registra en el logger `sigah.calidad` (sin datos personales).
"""
import logging
import re
from datetime import date, datetime, time, timedelta
from enum import Enum

from .modelos import ZONA, Cita, EstadoCita, Paciente

# 1: confirmado contra la interfaz de SIGAH. 2 y 3: observados al confirmar y anular citas de prueba.
ESTADOS = {1: EstadoCita.AGENDADA, 2: EstadoCita.CONFIRMADA, 3: EstadoCita.CANCELADA}

log = logging.getLogger("sigah.calidad")


class ProblemaCalidad(Enum):
    """Problemas de un registro SIGAH. El valor es un código estable: se guarda y se consulta por él, no por el texto."""
    CITA_DESCARTADA = "cita_descartada"  # sin id o sin FEC_HORA válida
    ESTADO_NO_CATALOGADO = "estado_no_catalogado"
    CENTRO_INVALIDO = "centro_invalido"
    RUT_INVALIDO = "rut_invalido"
    RUT_DV_INVALIDO = "rut_dv_invalido"
    TELEFONO_INVALIDO = "telefono_invalido"
    NOMBRE_AUSENTE = "nombre_ausente"
    NOMBRE_SIN_SEPARADOR = "nombre_sin_separador"


def _avisar(id_: str | None, problema: ProblemaCalidad, mensaje: str, nivel: int = logging.WARNING) -> None:
    """Registra un problema: texto legible en el log, y aparte el código y el id, para guardarlos y consultarlos."""
    log.log(nivel, "%s: %s", id_ or "?", mensaje, extra={"problema": problema, "cita_id": id_})


def dias_sigah(fecha: date, desfase_horas: int) -> list[date]:
    """Días que hay que pedir a SIGAH para cubrir el día local `fecha` (con +4 h: ese día y el siguiente)."""
    inicio = datetime.combine(fecha, time()) + timedelta(hours=desfase_horas)
    fin = inicio + timedelta(days=1) - timedelta(seconds=1)
    return sorted({inicio.date(), fin.date()})


def citas_de_fechas(registros: list[dict], fechas: set[date], desfase_horas: int) -> list[Cita]:
    """Mapea solo los registros cuyo inicio cae en alguna de las `fechas` locales."""
    citas = []
    for reg in registros:
        inicio = _inicio(reg.get("FEC_HORA"), desfase_horas)
        if inicio is not None and inicio.date() not in fechas:
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
        _avisar(id_, ProblemaCalidad.CITA_DESCARTADA, "cita descartada: falta id o FEC_HORA válida", logging.ERROR)
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
        _avisar(id_, ProblemaCalidad.ESTADO_NO_CATALOGADO, f"COD_EST desconocido ({valor!r})")
        return EstadoCita.DESCONOCIDO
    return estado


def _centro(id_: str, valor) -> int | None:
    """Acepta 3 o "3"; cualquier otro valor queda en None."""
    if isinstance(valor, int) and not isinstance(valor, bool):  # bool es subclase de int: True no es un centro
        return valor
    if isinstance(valor, str) and valor.strip().isdecimal():
        return int(valor)
    _avisar(id_, ProblemaCalidad.CENTRO_INVALIDO, "CENTRO ausente o no interpretable")
    return None


def _rut(id_: str, valor) -> str | None:
    texto = (_texto(valor) or "").replace(".", "").replace(" ", "").upper()
    m = re.fullmatch(r"(\d{7,8})-?([\dK])", texto)
    if not m:
        _avisar(id_, ProblemaCalidad.RUT_INVALIDO, "RUT ausente o con formato inválido")
        return None
    cuerpo, dv = m.groups()
    if dv != _dv(cuerpo):
        _avisar(id_, ProblemaCalidad.RUT_DV_INVALIDO, "RUT con dígito verificador inválido")
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
        _avisar(id_, ProblemaCalidad.TELEFONO_INVALIDO, "teléfono ausente o no interpretable")
        return None
    return f"+56{digitos}"


def _nombre(id_: str, valor) -> tuple[str | None, str | None]:
    """SIGAH entrega "APELLIDOS, NOMBRES"."""
    texto = _texto(valor)
    if texto is None:
        _avisar(id_, ProblemaCalidad.NOMBRE_AUSENTE, "nombre de paciente ausente")
        return None, None
    apellidos, coma, nombres = texto.partition(",")
    if not coma:
        _avisar(id_, ProblemaCalidad.NOMBRE_SIN_SEPARADOR, "nombre sin separador de apellidos")
        return None, texto
    return _texto(apellidos), _texto(nombres)
