"""Cliente HTTP de la API de agenda SIGAH."""
import re
import time
from datetime import date, timedelta

import httpx

from .auditoria import Auditoria
from .errores import (POR_CODIGO, AutenticacionError, EscrituraNoPermitidaError, RespuestaInesperadaError,
                      ResultadoInciertoError, ServicioNoDisponibleError, SigahError, SolicitudInvalidaError)
from .mapeo import a_cita, citas_de_fechas, dias_sigah
from .modelos import Cita, EstadoCita

# Valores por defecto: con ellos basta configurar la API key. Todos se pueden cambiar.
URL_BASE = "https://sigah-entrevista-79007222944.southamerica-west1.run.app/api/v1"  # ambiente entregado
CENTRO_ID = 3  # Hospital, según Informática
DESFASE_HORAS = 4  # SIGAH entrega la hora local + 4 h (HALLAZGOS §1.1)
TIMEOUT_LECTURA = 10.0  # segundos
TIMEOUT_ESCRITURA = 60.0  # segundos: confirmar/anular tardaron hasta 25 s en producción
REINTENTOS = 3  # solo lecturas; las escrituras nunca se reintentan
ESPERA_REINTENTO = 1.0  # segundos; se duplica en cada reintento (1, 2, 4)
MAX_PAGINAS = 100  # tope de seguridad: páginas de 50 citas, el día más cargado observado tuvo 3
MAX_DIAS = 31  # tope de `agenda(dias=...)`: un error de tipeo no debe lanzar miles de peticiones a producción

# Estados desde los que se permite cada escritura (SIGAH rechaza el resto con ERR-07 / ERR-09).
PUEDE_CONFIRMAR = frozenset({EstadoCita.AGENDADA})
PUEDE_ANULAR = frozenset({EstadoCita.AGENDADA, EstadoCita.CONFIRMADA})

# Una clave fuera de estas es un cambio de formato no documentado: se falla antes que devolver datos parciales.
CLAVES_LISTA = {"estado", "total", "citas", "siguiente"}  # "siguiente": token de la próxima página
CLAVES_DETALLE = {"estado", "cita"}

MAX_RETRY_AFTER = 60  # segundos: nunca esperar más, aunque SIGAH pida más en Retry-After


class _Saturado(Exception):
    """HTTP 429: SIGAH rechazó la petición por exceso de tráfico, sin procesarla."""

    def __init__(self, espera: float | None):
        super().__init__("HTTP 429 demasiadas peticiones")
        self.espera = espera  # segundos pedidos en Retry-After, o None


class _Transitorio(Exception):
    """Falla de red o HTTP 5xx: no se sabe si SIGAH procesó la petición."""


class SigahClient:
    """Cliente de SIGAH: expone las citas en el modelo propio (`Cita`).

    Uso: `with SigahClient(api_key) as cliente: cliente.agenda(date(2026, 12, 15))`.
    La escritura está deshabilitada salvo `permitir_escritura=True`.
    """

    def __init__(self, api_key: str, *, url_base: str = URL_BASE, centro_id: int = CENTRO_ID,
                 desfase_horas: int = DESFASE_HORAS, permitir_escritura: bool = False,
                 auditoria: Auditoria | None = None, timeout: float = TIMEOUT_LECTURA,
                 timeout_escritura: float = TIMEOUT_ESCRITURA, reintentos: int = REINTENTOS,
                 espera: float = ESPERA_REINTENTO):
        self.centro_id = centro_id
        self.desfase_horas = desfase_horas
        self.permitir_escritura = permitir_escritura
        self._auditoria = auditoria
        self._timeout_escritura = timeout_escritura
        self._reintentos = reintentos
        self._espera = espera
        self._http = httpx.Client(base_url=url_base, timeout=timeout, headers={"X-Auth-Token": api_key})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._http.close()

    def agenda(self, fecha: date, dias: int = 1) -> list[Cita]:
        """Citas de `fecha` y los `dias - 1` días siguientes, en hora local de Chile, ordenadas por inicio."""
        if not 1 <= dias <= MAX_DIAS:
            raise ValueError(f"dias debe estar entre 1 y {MAX_DIAS}, no {dias}")
        return self._entregar("agenda", {"fecha": fecha, "dias": dias}, lambda: self._agenda(fecha, dias))

    def cita(self, id_cita: str) -> Cita:
        """Una cita por su identificador (ej. "AGD-0000099013")."""
        return self._entregar("cita", {"id": id_cita}, lambda: self._leer_cita(id_cita))

    def confirmar(self, id_cita: str) -> Cita:
        """Confirma una cita (ver PUEDE_CONFIRMAR). Devuelve la cita releída desde SIGAH."""
        return self._entregar("confirmar", {"id": id_cita},
                              lambda: self._escribir(id_cita, "confirmar", PUEDE_CONFIRMAR))

    def anular(self, id_cita: str) -> Cita:
        """Anula una cita (ver PUEDE_ANULAR). Devuelve la cita releída desde SIGAH."""
        return self._entregar("anular", {"id": id_cita}, lambda: self._escribir(id_cita, "anular", PUEDE_ANULAR))

    def _entregar(self, operacion: str, parametros: dict, obtener):
        """Ejecuta una operación pública y audita lo que entrega (o el error que informa) y los avisos de calidad."""
        if self._auditoria is None:
            return obtener()
        with self._auditoria.capturar_calidad():
            try:
                resultado = obtener()
            except SigahError as e:
                self._auditoria.registrar_salida(operacion, parametros, error=f"{type(e).__name__}: {e}")
                raise
        self._auditoria.registrar_salida(operacion, parametros, resultado)
        return resultado

    def _agenda(self, fecha: date, dias: int) -> list[Cita]:
        fechas = {fecha + timedelta(days=i) for i in range(dias)}
        # Días locales consecutivos comparten días de SIGAH: cada uno se pide una sola vez.
        dias_a_pedir = sorted({d for f in fechas for d in dias_sigah(f, self.desfase_horas)})
        citas = []
        for dia in dias_a_pedir:
            citas += citas_de_fechas(self._registros(dia), fechas, self.desfase_horas)
        return sorted(citas, key=lambda c: c.inicio)

    def _registros(self, dia: date) -> list[dict]:
        """Todos los registros de un día SIGAH, recorriendo las páginas (`siguiente` → parámetro `desde`)."""
        params = {"fecha": f"{dia} 00:00:00", "centro_id": self.centro_id}
        registros, tokens = [], set()
        while True:
            datos = self._get("/citas", params)
            registros += _extraer_citas(datos)
            token = datos.get("siguiente")
            if not token:
                return registros
            if token in tokens or len(tokens) >= MAX_PAGINAS:
                raise RespuestaInesperadaError(f"La paginación de {dia} no termina (token repetido o demasiadas páginas)")
            tokens.add(token)
            params = {**params, "desde": token}

    def _leer_cita(self, id_cita: str) -> Cita:
        # El id va dentro de la URL: sin esto, "AGD-1/anular" haría un GET a otra ruta.
        if not re.fullmatch(r"[A-Za-z0-9-]+", id_cita):
            raise SolicitudInvalidaError(f"Id de cita inválido: {id_cita!r}")
        datos = self._get(f"/citas/{id_cita}")
        cita = a_cita(_extraer_cita(datos), self.desfase_horas)
        if cita is None:
            raise RespuestaInesperadaError(f"SIGAH devolvió {id_cita} sin id o fecha válida")
        return cita

    def _escribir(self, id_cita: str, accion: str, estados_validos: frozenset[EstadoCita]) -> Cita:
        if not self.permitir_escritura:
            raise EscrituraNoPermitidaError("La escritura está deshabilitada")
        # Se relee justo antes de escribir: el estado pudo cambiar desde que se obtuvo la agenda.
        actual = self._leer_cita(id_cita)
        if actual.estado not in estados_validos:
            raise EscrituraNoPermitidaError(f"{id_cita} está {actual.estado.value}; no se puede {accion}")

        peticion = self._http.build_request("POST", f"/citas/{id_cita}/{accion}", timeout=self._timeout_escritura)
        self._auditar(peticion, "intento")
        # Nunca se reintenta: anular notifica al paciente y repetirlo podría duplicar el efecto.
        try:
            respuesta = self._enviar(peticion)
        except _Transitorio as e:
            raise self._incierto(id_cita, accion, e) from e
        except _Saturado as e:  # a diferencia de un timeout, se sabe que NO se aplicó
            raise ServicioNoDisponibleError(f"SIGAH rechazó '{accion}' de {id_cita} por exceso de tráfico "
                                            f"(429): no se aplicó, reintentar más tarde") from e
        _validar(respuesta)
        return self._leer_cita(id_cita)

    def _incierto(self, id_cita: str, accion: str, causa: Exception) -> ResultadoInciertoError:
        try:
            estado = self._leer_cita(id_cita).estado.value
        except SigahError:
            estado = "no disponible"
        return ResultadoInciertoError(f"No se sabe si se aplicó '{accion}' a {id_cita} ({causa}); estado observado: "
                                      f"{estado}, pero SIGAH puede aplicarlo con retraso. Revisar antes de reintentar.")

    def _get(self, ruta: str, params: dict | None = None) -> dict:
        peticion = self._http.build_request("GET", ruta, params=params)
        espera_pedida = None
        for intento in range(self._reintentos + 1):
            if intento:
                time.sleep(espera_pedida if espera_pedida is not None else self._espera * 2 ** (intento - 1))
            try:
                return _validar(self._enviar(peticion))
            except _Transitorio as e:
                causa, espera_pedida = e, None  # el Retry-After de un 429 anterior no aplica a esta falla
            except _Saturado as e:
                causa, espera_pedida = e, e.espera
        raise ServicioNoDisponibleError(f"SIGAH no responde ({causa})")

    def _enviar(self, peticion: httpx.Request) -> httpx.Response:
        """Envía y audita. Lanza `_Transitorio` ante falla de red o HTTP 5xx, y `_Saturado` ante HTTP 429."""
        try:
            respuesta = self._http.send(peticion)
        except httpx.TransportError as e:
            self._auditar(peticion, "error", error=repr(e))
            raise _Transitorio(repr(e)) from e
        self._auditar(peticion, "respuesta", respuesta)
        if respuesta.status_code == 429:
            raise _Saturado(_retry_after(respuesta))
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
        # Las escrituras responden en texto plano: "OK" o un código (ej. "ERR-07").
        texto = respuesta.text.strip()
        if texto == "OK" and respuesta.status_code == 200:
            return {"estado": "OK"}
        if re.fullmatch(r"ERR-\d+", texto):
            raise POR_CODIGO.get(texto, SigahError)(f"SIGAH respondió {texto}", texto) from None
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


def _retry_after(respuesta: httpx.Response) -> float | None:
    """Segundos de la cabecera Retry-After, con tope. None si no viene o no está en segundos (puede ser una fecha)."""
    valor = respuesta.headers.get("Retry-After", "").strip()
    return min(float(valor), MAX_RETRY_AFTER) if valor.isdecimal() else None


def _extraer_citas(datos: dict) -> list[dict]:
    """De `{"estado", "total", "citas": [...], "siguiente"?}` devuelve los registros de la página, validando la forma."""
    _exigir_claves(datos, CLAVES_LISTA)
    registros = datos.get("citas")
    # "total" es la cantidad de esta página, no la del día.
    if not isinstance(registros, list) or datos.get("total") != len(registros):
        raise RespuestaInesperadaError("Lista de citas inconsistente con 'total'")
    return registros


def _extraer_cita(datos: dict) -> dict:
    """De `{"estado", "cita": {...}}` devuelve el registro de la cita, validando la forma."""
    _exigir_claves(datos, CLAVES_DETALLE)
    return datos.get("cita") or {}


def _exigir_claves(datos: dict, esperadas: set[str]) -> None:
    extra = set(datos) - esperadas
    if extra:
        raise RespuestaInesperadaError(f"Claves no reconocidas en la respuesta: {sorted(extra)}")
