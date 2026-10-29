"""Modelo de dominio, independiente de los nombres de campos de SIGAH."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Santiago")


class EstadoCita(Enum):
    AGENDADA = "agendada"
    CONFIRMADA = "confirmada"
    CANCELADA = "cancelada"
    DESCONOCIDO = "desconocido"


@dataclass(frozen=True)
class Paciente:
    rut: str | None = None
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
    email: str | None = None  # el manual lo define, pero SIGAH no lo entrega hoy


@dataclass(frozen=True)
class Cita:
    id: str
    inicio: datetime  # en ZONA
    estado: EstadoCita
    paciente: Paciente
    especialidad: str | None = None  # código, ej. "MINT"
    especialidad_nombre: str | None = None
    profesional: str | None = None
    centro_id: int | None = None
