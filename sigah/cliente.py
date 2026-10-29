"""Cliente HTTP de la API de agenda SIGAH."""
import re
import time
from datetime import date

import httpx

from .auditoria import Auditoria
from .errores import (POR_CODIGO, AutenticacionError, EscrituraNoPermitidaError, RespuestaInesperadaError,
                      ResultadoInciertoError, ServicioNoDisponibleError, SigahError, SolicitudInvalidaError)
from .mapeo import a_cita, citas_del_dia, dias_sigah
from .modelos import Cita, EstadoCita

URL_BASE = "https://sigah-entrevista-79007222944.southamerica-west1.run.app/api/v1"
# Una clave fuera de estas podría ser el token de paginación (no documentado): se falla antes que devolver datos parciales.
CLAVES_LISTA = {"estado", "total", "citas"}
CLAVES_DETALLE = {"estado", "cita"}


class _Transitorio(Exception):
    """Falla de red o HTTP 5xx: no se sabe si SIGAH procesó la petición."""


class SigahClient:
    """Cliente de SIGAH: expone las citas en el modelo propio (`Cita`).

    Uso: `with SigahClient(api_key, centro_id=3) as cliente: cliente.agenda(date(2026, 12, 15))`.
    La escritura está deshabilitada salvo `permitir_escritura=True`.
    """

    def __init__(self, api_key: str, centro_id: int, *, url_base: str = URL_BASE, desfase_horas: int = 4,
                 permitir_escritura: bool = False, auditoria: Auditoria | None = None,
                 timeout: float = 10.0, reintentos: int = 3, espera: float = 1.0):
        self.centro_id = centro_id
        self.desfase_horas = desfase_horas
        self.permitir_escritura = permitir_escritura
        self._auditoria = auditoria
        self._reintentos = reintentos
        self._espera = espera
        self._http = httpx.Client(base_url=url_base, timeout=timeout, headers={"X-Auth-Token": api_key})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._http.close()

    def agenda(self, fecha: date) -> list[Cita]:
        """Citas del día `fecha` en hora local de Chile, ordenadas por inicio."""
        citas = []
        for dia in dias_sigah(fecha, self.desfase_horas):
            datos = self._get("/citas", {"fecha": f"{dia} 00:00:00", "centro_id": self.centro_id})
            citas += citas_del_dia(_lista(datos), fecha, self.desfase_horas)
        return sorted(citas, key=lambda c: c.inicio)

    def cita(self, id_cita: str) -> Cita:
        """Una cita por su identificador (ej. "AGD-0000099013")."""
        if not re.fullmatch(r"[A-Za-z0-9-]+", id_cita):
            raise SolicitudInvalidaError(f"Id de cita inválido: {id_cita!r}")
        cita = a_cita(_detalle(self._get(f"/citas/{id_cita}")), self.desfase_horas)
        if cita is None:
            raise RespuestaInesperadaError(f"SIGAH devolvió {id_cita} sin id o fecha válida")
        return cita

    def confirmar(self, id_cita: str) -> Cita:
        """Confirma una cita AGENDADA. Devuelve la cita releída desde SIGAH."""
        return self._escribir(id_cita, "confirmar", {EstadoCita.AGENDADA})

    def anular(self, id_cita: str) -> Cita:
        """Anula una cita AGENDADA o CONFIRMADA. Devuelve la cita releída desde SIGAH."""
        return self._escribir(id_cita, "anular", {EstadoCita.AGENDADA, EstadoCita.CONFIRMADA})

    def _escribir(self, id_cita: str, accion: str, estados_validos: set[EstadoCita]) -> Cita:
        if not self.permitir_escritura:
            raise EscrituraNoPermitidaError("La escritura está deshabilitada")
        # Se relee justo antes de escribir: el estado pudo cambiar desde que se obtuvo la agenda.
        actual = self.cita(id_cita)
        if actual.estado not in estados_validos:
            raise EscrituraNoPermitidaError(f"{id_cita} está {actual.estado.value}; no se puede {accion}")

        peticion = self._http.build_request("POST", f"/citas/{id_cita}/{accion}")
        self._auditar(peticion, "intento")
        # Nunca se reintenta: anular notifica al paciente y repetirlo podría duplicar el efecto.
        try:
            respuesta = self._enviar(peticion)
        except _Transitorio as e:
            raise self._incierto(id_cita, accion, e) from e
        _validar(respuesta)
        return self.cita(id_cita)

    def _incierto(self, id_cita: str, accion: str, causa: Exception) -> ResultadoInciertoError:
        try:
            estado = self.cita(id_cita).estado.value
        except SigahError:
            estado = "no disponible"
        return ResultadoInciertoError(f"No se sabe si se aplicó '{accion}' a {id_cita} ({causa}); "
                                      f"estado observado: {estado}. Revisar antes de reintentar.")

    def _get(self, ruta: str, params: dict | None = None) -> dict:
        peticion = self._http.build_request("GET", ruta, params=params)
        for intento in range(self._reintentos + 1):
            if intento:
                time.sleep(self._espera * 2 ** (intento - 1))
            try:
                return _validar(self._enviar(peticion))
            except _Transitorio as e:
                causa = e
        raise ServicioNoDisponibleError(f"SIGAH no responde ({causa})")

    def _enviar(self, peticion: httpx.Request) -> httpx.Response:
        """Envía y audita. Lanza `_Transitorio` ante falla de red o HTTP 5xx."""
        try:
            respuesta = self._http.send(peticion)
        except httpx.TransportError as e:
            self._auditar(peticion, "error", error=repr(e))
            raise _Transitorio(repr(e)) from e
        self._auditar(peticion, "respuesta", respuesta)
        if respuesta.status_code >= 500:
            raise _Transitorio(f"HTTP {respuesta.status_code}")
        return respuesta

    def _auditar(self, peticion: httpx.Request, fase: str, respuesta: httpx.Response | None = None,
                 error: str | None = None) -> None:
        if self._auditoria is None:
            return
        detalle = {}
        if respuesta is not None:
            detalle = {"http_status": respuesta.status_code, "cuerpo": respuesta.text,
                       "trace": respuesta.headers.get("x-cloud-trace-context")}
        self._auditoria.registrar(peticion.method, str(peticion.url), fase, error=error, **detalle)


def _validar(respuesta: httpx.Response) -> dict:
    """Devuelve el cuerpo si SIGAH respondió OK; si no, lanza el error que corresponde."""
    try:
        datos = respuesta.json()
    except ValueError:
        raise RespuestaInesperadaError(f"HTTP {respuesta.status_code}: respuesta no es JSON") from None
    if not isinstance(datos, dict):
        raise RespuestaInesperadaError(f"HTTP {respuesta.status_code}: se esperaba un objeto JSON")

    codigo, mensaje = datos.get("codigo"), datos.get("msg") or f"HTTP {respuesta.status_code}"
    if respuesta.status_code in (401, 403):
        raise AutenticacionError(mensaje, codigo)
    # SIGAH informa errores de negocio con HTTP 200 y estado "ERROR".
    if datos.get("estado") == "ERROR":
        raise POR_CODIGO.get(codigo, SigahError)(mensaje, codigo)
    if respuesta.status_code == 422:
        raise SolicitudInvalidaError(f"Parámetros rechazados: {datos.get('detail')}")
    if respuesta.status_code >= 400 or datos.get("estado") != "OK":
        raise RespuestaInesperadaError(f"HTTP {respuesta.status_code}, estado {datos.get('estado')!r}")
    return datos


def _lista(datos: dict) -> list[dict]:
    _exigir_claves(datos, CLAVES_LISTA)
    registros = datos.get("citas")
    if not isinstance(registros, list) or datos.get("total") != len(registros):
        raise RespuestaInesperadaError("Lista de citas inconsistente con 'total'")
    return registros


def _detalle(datos: dict) -> dict:
    _exigir_claves(datos, CLAVES_DETALLE)
    return datos.get("cita") or {}


def _exigir_claves(datos: dict, esperadas: set[str]) -> None:
    if extra := set(datos) - esperadas:
        raise RespuestaInesperadaError(f"Claves no reconocidas en la respuesta: {sorted(extra)}")
