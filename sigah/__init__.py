"""Cliente de la API de agenda SIGAH."""
from .auditoria import Auditoria
from .cliente import SigahClient
from .errores import (AutenticacionError, CitaNoEncontradaError, EscrituraNoPermitidaError,
                      RespuestaInesperadaError, ResultadoInciertoError, ServicioNoDisponibleError,
                      SigahError, SolicitudInvalidaError)
from .mapeo import ProblemaCalidad
from .modelos import Cita, EstadoCita, Paciente
from .reglas import Alerta, TipoAlerta, revisar

__all__ = [
    "SigahClient", "Auditoria", "Cita", "EstadoCita", "Paciente", "Alerta", "TipoAlerta", "ProblemaCalidad", "revisar",
    "SigahError", "AutenticacionError", "SolicitudInvalidaError", "CitaNoEncontradaError",
    "RespuestaInesperadaError", "ServicioNoDisponibleError", "EscrituraNoPermitidaError",
    "ResultadoInciertoError",
]
