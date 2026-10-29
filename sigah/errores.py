"""Excepciones del cliente SIGAH."""


class SigahError(Exception):
    """Error base. `codigo` es el código SIGAH (ej. "ERR-04") cuando existe."""

    def __init__(self, mensaje: str, codigo: str | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


class AutenticacionError(SigahError):
    """API key ausente, inválida o expirada (ERR-01)."""


class SolicitudInvalidaError(SigahError):
    """Parámetros rechazados por SIGAH (ERR-02, ERR-03, HTTP 422)."""


class CitaNoEncontradaError(SigahError):
    """La cita no existe (ERR-04)."""


class RespuestaInesperadaError(SigahError):
    """Respuesta con un formato que el cliente no sabe interpretar con seguridad."""


class ServicioNoDisponibleError(SigahError):
    """SIGAH no respondió después de agotar los reintentos."""


class EscrituraNoPermitidaError(SigahError):
    """Escritura deshabilitada o no válida para el estado actual de la cita."""


class ResultadoInciertoError(SigahError):
    """La escritura se envió, pero no se sabe si SIGAH la aplicó. Requiere revisión manual."""


POR_CODIGO = {
    "ERR-01": AutenticacionError,
    "ERR-02": SolicitudInvalidaError,
    "ERR-03": SolicitudInvalidaError,
    "ERR-04": CitaNoEncontradaError,
}
