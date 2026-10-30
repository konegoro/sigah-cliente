"""Reglas de negocio sobre una agenda: detectan situaciones a revisar, sin modificar ni descartar citas.

La API no informa la duración de las citas: los topes se detectan solo por inicio idéntico.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

from .modelos import ZONA, Cita, EstadoCita

PROFESIONALES_GRUPALES = ("EQUIPO",)  # ej. "EQUIPO TURNO 3": atiende a varios pacientes a la vez
# Rango horario plausible por defecto (hora local). Lo observado va de 08:00 a 20:30.
HORA_MIN = time(7)
HORA_MAX = time(21)


class TipoAlerta(Enum):
    PACIENTE_MISMA_HORA = "paciente_misma_hora"
    PACIENTE_MISMA_ESPECIALIDAD_DIA = "paciente_misma_especialidad_dia"
    PROFESIONAL_MISMA_HORA = "profesional_misma_hora"
    SIN_CONTACTO = "sin_contacto"
    ESTADO_DESCONOCIDO = "estado_desconocido"
    HORARIO_FUERA_DE_RANGO = "horario_fuera_de_rango"
    CITA_PASADA = "cita_pasada"


@dataclass(frozen=True)
class Alerta:
    tipo: TipoAlerta
    cita_ids: tuple[str, ...]
    detalle: str


def revisar(citas: list[Cita], *, hora_min: time = HORA_MIN, hora_max: time = HORA_MAX,
            revisar_profesional: bool = False, ahora: datetime | None = None) -> list[Alerta]:
    """Revisa las citas y devuelve las alertas encontradas.

    `revisar_profesional` viene apagado: SIGAH identifica al profesional solo por nombre
    abreviado, así que dos médicos homónimos generarían falsos positivos.
    """
    ahora = ahora or datetime.now(ZONA)
    alertas = []
    for c in citas:
        if c.paciente.telefono is None:
            alertas.append(Alerta(TipoAlerta.SIN_CONTACTO, (c.id,), "sin teléfono válido"))
        if c.estado is EstadoCita.DESCONOCIDO:
            alertas.append(Alerta(TipoAlerta.ESTADO_DESCONOCIDO, (c.id,), "estado no catalogado"))
        if not hora_min <= c.inicio.time() <= hora_max:
            alertas.append(Alerta(TipoAlerta.HORARIO_FUERA_DE_RANGO, (c.id,),
                                  f"inicio {c.inicio:%H:%M} fuera de {hora_min:%H:%M}-{hora_max:%H:%M}"))
        if c.inicio < ahora:
            alertas.append(Alerta(TipoAlerta.CITA_PASADA, (c.id,), f"inicio {c.inicio:%Y-%m-%d %H:%M} ya pasó"))

    alertas += _repetidas(citas, TipoAlerta.PACIENTE_MISMA_HORA, "mismo paciente, misma hora",
                          lambda c: (c.paciente.rut, c.inicio))
    alertas += _repetidas(citas, TipoAlerta.PACIENTE_MISMA_ESPECIALIDAD_DIA,
                          "mismo paciente, misma especialidad, mismo día",
                          lambda c: (c.paciente.rut, c.especialidad, c.inicio.date()))
    if revisar_profesional:
        individuales = [c for c in citas if not (c.profesional or "").upper().startswith(PROFESIONALES_GRUPALES)]
        alertas += _repetidas(individuales, TipoAlerta.PROFESIONAL_MISMA_HORA, "mismo profesional, misma hora",
                              lambda c: (c.profesional, c.inicio))
    return alertas


def _repetidas(citas: list[Cita], tipo: TipoAlerta, detalle: str, clave) -> list[Alerta]:
    """Agrupa las citas por `clave(cita)` y alerta cada grupo con más de una cita.

    Ej.: clave = lambda c: (c.paciente.rut, c.inicio) junta las citas del mismo paciente a la misma hora.
    Si a la clave le falta un dato (None), la cita no participa.
    """
    grupos = defaultdict(list)  # clave → ids de las citas con esa clave
    for c in citas:
        k = clave(c)
        if None not in k:
            grupos[k].append(c.id)

    alertas = []
    for ids in grupos.values():
        if len(ids) > 1:
            alertas.append(Alerta(tipo, tuple(ids), detalle))
    return alertas
