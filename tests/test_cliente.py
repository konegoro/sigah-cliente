"""Comportamiento HTTP del cliente contra un SIGAH simulado. Datos inventados."""
from datetime import date

import httpx
import pytest

from sigah import (Auditoria, AutenticacionError, CitaNoEncontradaError, EscrituraNoPermitidaError,
                   EstadoCita, RespuestaInesperadaError, ResultadoInciertoError, ServicioNoDisponibleError,
                   SigahClient, SigahError)

URL = "https://sigah.test/api/v1"
pytestmark = pytest.mark.respx(base_url=URL, assert_all_called=False)

REGISTRO = {"ID_CITA": "AGD-1", "RUT_PAC": "12.345.678-5", "NOM_PAC": "PEREZ, JUAN",
            "FEC_HORA": "2026-12-15 12:00:00", "COD_EST": 1, "TEL_PAC": "+56 9 1234 5678"}
HTML_502 = httpx.Response(502, text="<html>502 Bad Gateway</html>")


def cliente(**kwargs):
    return SigahClient("clave", url_base=URL, espera=0, **kwargs)


def lista(*registros):
    return httpx.Response(200, json={"estado": "OK", "total": len(registros), "citas": list(registros)})


def detalle(registro=REGISTRO):
    return httpx.Response(200, json={"estado": "OK", "cita": registro})


def test_error_de_negocio_con_http_200(respx_mock):
    respx_mock.get("/citas/AGD-9").respond(200, json={"estado": "ERROR", "codigo": "ERR-04", "msg": "no existe"})
    with pytest.raises(CitaNoEncontradaError):
        cliente().cita("AGD-9")


def test_credencial_expirada(respx_mock):
    respx_mock.get("/citas/AGD-1").respond(
        403, json={"estado": "ERROR", "codigo": "ERR-01", "msg": "credencial expirada"})
    with pytest.raises(AutenticacionError):
        cliente().cita("AGD-1")


def test_get_reintenta_502_en_html(respx_mock):
    ruta = respx_mock.get("/citas/AGD-1").mock(side_effect=[HTML_502, HTML_502, detalle()])
    assert cliente().cita("AGD-1").id == "AGD-1"
    assert ruta.call_count == 3


def test_get_agota_reintentos(respx_mock):
    respx_mock.get("/citas/AGD-1").mock(side_effect=httpx.ConnectTimeout("timeout"))
    with pytest.raises(ServicioNoDisponibleError):
        cliente(reintentos=2).cita("AGD-1")


@pytest.mark.parametrize("retry_after, espera", [
    ("7", 7),                               # segundos: se respeta
    ("3600", 60),                           # sobre el tope: se limita a MAX_RETRY_AFTER
    ("Wed, 21 Oct 2026 07:28:00 GMT", 0),   # fecha: se ignora y rige el backoff normal (0 en estos tests)
])
def test_get_reintenta_429_respetando_retry_after(respx_mock, monkeypatch, retry_after, espera):
    esperas = []
    monkeypatch.setattr("sigah.cliente.time.sleep", esperas.append)  # registra la espera en vez de dormir
    respx_mock.get("/citas/AGD-1").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": retry_after}), detalle()])
    assert cliente().cita("AGD-1").id == "AGD-1"
    assert esperas == [espera]


def test_retry_after_solo_aplica_a_la_falla_que_lo_pidio(respx_mock, monkeypatch):
    esperas = []
    monkeypatch.setattr("sigah.cliente.time.sleep", esperas.append)
    respx_mock.get("/citas/AGD-1").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}), HTML_502, detalle()])
    SigahClient("clave", url_base=URL, espera=1).cita("AGD-1")
    assert esperas == [7, 2]  # tras el 502 vuelve el backoff normal (1, 2, 4), no los 7 s del 429


def test_post_con_429_no_se_aplico_y_no_es_incierto(respx_mock):
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle())
    post = respx_mock.post("/citas/AGD-1/confirmar").respond(429)
    with pytest.raises(ServicioNoDisponibleError, match="no se aplicó"):
        cliente(permitir_escritura=True).confirmar("AGD-1")
    assert post.call_count == 1  # tampoco se reintenta


def test_clave_desconocida_falla_en_vez_de_devolver_datos_parciales(respx_mock):
    respx_mock.get("/citas").respond(
        200, json={"estado": "OK", "total": 1, "citas": [REGISTRO], "cursor": "abc"})
    with pytest.raises(RespuestaInesperadaError, match="cursor"):
        cliente().agenda(date(2026, 12, 15))


def pagina(*ids, siguiente=None):
    datos = {"estado": "OK", "total": len(ids), "citas": [{**REGISTRO, "ID_CITA": i} for i in ids]}
    return httpx.Response(200, json=datos | ({"siguiente": siguiente} if siguiente else {}))


def test_agenda_recorre_todas_las_paginas(respx_mock):
    # Como en producción (07-10): "siguiente" trae el token que se envía en "desde".
    paginas = {None: pagina("P1-A", "P1-B", siguiente="PAG-1"), "PAG-1": pagina("P2-A", siguiente="PAG-2"),
               "PAG-2": pagina("P3-A")}
    respx_mock.get("/citas").mock(side_effect=lambda req: (
        paginas[req.url.params.get("desde")] if req.url.params["fecha"].startswith("2026-12-15") else lista()))
    assert sorted(c.id for c in cliente().agenda(date(2026, 12, 15))) == ["P1-A", "P1-B", "P2-A", "P3-A"]


def test_paginacion_que_no_termina(respx_mock):
    respx_mock.get("/citas").mock(return_value=pagina("A", siguiente="PAG-1"))  # siempre el mismo token
    with pytest.raises(RespuestaInesperadaError, match="no termina"):
        cliente().agenda(date(2026, 12, 15))


def test_agenda_une_dos_dias_sigah_y_filtra_por_dia_local(respx_mock):
    # Día local 15-12 = SIGAH 15-12 04:00 a 16-12 03:59 (desfase +4 h).
    por_dia = {
        "2026-12-15 00:00:00": lista({**REGISTRO, "ID_CITA": "ANTES", "FEC_HORA": "2026-12-15 02:00:00"},
                                     {**REGISTRO, "ID_CITA": "MANANA", "FEC_HORA": "2026-12-15 12:00:00"}),
        "2026-12-16 00:00:00": lista({**REGISTRO, "ID_CITA": "NOCHE", "FEC_HORA": "2026-12-16 01:30:00"},
                                     {**REGISTRO, "ID_CITA": "DESPUES", "FEC_HORA": "2026-12-16 12:00:00"}),
    }
    ruta = respx_mock.get("/citas").mock(side_effect=lambda req: por_dia[req.url.params["fecha"]])
    citas = cliente().agenda(date(2026, 12, 15))
    assert [c.id for c in citas] == ["MANANA", "NOCHE"]
    assert {c.request.url.params["centro_id"] for c in ruta.calls} == {"3"}


def test_agenda_de_varios_dias_pide_cada_dia_sigah_una_sola_vez(respx_mock):
    # Días locales 15 y 16 = días SIGAH 15, 16 y 17; el 16 lo necesitan ambos, pero se pide una vez.
    por_dia = {
        "2026-12-15 00:00:00": lista({**REGISTRO, "ID_CITA": "D14-NOCHE", "FEC_HORA": "2026-12-15 02:00:00"},
                                     {**REGISTRO, "ID_CITA": "D15", "FEC_HORA": "2026-12-15 12:00:00"}),
        "2026-12-16 00:00:00": lista({**REGISTRO, "ID_CITA": "D16", "FEC_HORA": "2026-12-16 12:00:00"}),
        "2026-12-17 00:00:00": lista({**REGISTRO, "ID_CITA": "D16-NOCHE", "FEC_HORA": "2026-12-17 01:00:00"},
                                     {**REGISTRO, "ID_CITA": "D17", "FEC_HORA": "2026-12-17 12:00:00"}),
    }
    ruta = respx_mock.get("/citas").mock(side_effect=lambda req: por_dia[req.url.params["fecha"]])
    citas = cliente().agenda(date(2026, 12, 15), dias=2)
    assert [c.id for c in citas] == ["D15", "D16", "D16-NOCHE"]
    assert ruta.call_count == 3


@pytest.mark.parametrize("dias", [0, 32])
def test_agenda_rechaza_dias_fuera_de_rango_sin_llamar_a_sigah(respx_mock, dias):
    with pytest.raises(ValueError):
        cliente().agenda(date(2026, 12, 15), dias=dias)
    assert not respx_mock.calls


def test_total_inconsistente(respx_mock):
    respx_mock.get("/citas").respond(200, json={"estado": "OK", "total": 30, "citas": [REGISTRO]})
    with pytest.raises(RespuestaInesperadaError):
        cliente().agenda(date(2026, 12, 15))


def test_escritura_deshabilitada_por_defecto(respx_mock):
    with pytest.raises(EscrituraNoPermitidaError):
        cliente().confirmar("AGD-1")
    assert not respx_mock.calls


def test_no_confirma_si_el_estado_no_lo_permite(respx_mock):
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle({**REGISTRO, "COD_EST": 7}))
    post = respx_mock.post("/citas/AGD-1/confirmar")
    with pytest.raises(EscrituraNoPermitidaError):
        cliente(permitir_escritura=True).confirmar("AGD-1")
    assert not post.called


def test_escritura_exitosa_en_texto_plano(respx_mock):
    # Observado en producción: anular responde HTTP 200 con "OK" sin JSON.
    respx_mock.get("/citas/AGD-1").mock(side_effect=[detalle(), detalle({**REGISTRO, "COD_EST": 3})])
    respx_mock.post("/citas/AGD-1/anular").respond(200, text="OK")
    with Auditoria(":memory:") as auditoria:
        cita = cliente(permitir_escritura=True, auditoria=auditoria).anular("AGD-1")
        cuerpos_post = [r["cuerpo"] for r in auditoria.registros() if r["fase"] == "respuesta" and r["metodo"] == "POST"]
    assert cita.estado is EstadoCita.CANCELADA
    assert cuerpos_post == ["OK"]  # sin datos personales: queda en claro como evidencia


def test_codigo_de_error_en_texto_plano(respx_mock):
    # Observado en producción: re-confirmar una cita confirmada responde HTTP 200 con "ERR-07" sin JSON.
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle())
    respx_mock.post("/citas/AGD-1/confirmar").respond(200, text="ERR-07")
    with pytest.raises(SigahError) as error:
        cliente(permitir_escritura=True).confirmar("AGD-1")
    assert error.value.codigo == "ERR-07"


def test_post_no_se_reintenta_y_el_resultado_es_incierto(respx_mock):
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle())
    post = respx_mock.post("/citas/AGD-1/anular").mock(return_value=HTML_502)
    with pytest.raises(ResultadoInciertoError):
        cliente(permitir_escritura=True).anular("AGD-1")
    assert post.call_count == 1


def test_ok_sin_el_cambio_visible_es_incierto(respx_mock):
    # SIGAH puede aplicar con retraso (prueba A1): un OK con la cita aún agendada no es un éxito completo.
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle())  # antes y después: agendada
    post = respx_mock.post("/citas/AGD-1/confirmar").respond(200, text="OK")
    with pytest.raises(ResultadoInciertoError, match="aún figura agendada"):
        cliente(permitir_escritura=True).confirmar("AGD-1")
    assert post.call_count == 1  # tampoco se reintenta


def test_ok_sin_poder_releer_es_incierto(respx_mock):
    # SIGAH aceptó, pero la relectura falla: informar "no disponible" haría creer que no se aplicó.
    respx_mock.get("/citas/AGD-1").mock(side_effect=[detalle(), HTML_502, HTML_502, HTML_502, HTML_502])
    respx_mock.post("/citas/AGD-1/anular").respond(200, text="OK")
    with pytest.raises(ResultadoInciertoError, match="no se pudo releer"):
        cliente(permitir_escritura=True).anular("AGD-1")


def test_confirmar_audita_intento_y_respuesta_con_datos_enmascarados(respx_mock):
    respx_mock.get("/citas/AGD-1").mock(side_effect=[detalle(), detalle({**REGISTRO, "COD_EST": 2})])
    respx_mock.post("/citas/AGD-1/confirmar").respond(200, json={"estado": "OK"})
    with Auditoria(":memory:") as auditoria:
        cliente(permitir_escritura=True, auditoria=auditoria).confirmar("AGD-1")
        registros = auditoria.registros()

    assert [(r["metodo"], r["fase"]) for r in registros] == [
        ("GET", "respuesta"), ("POST", "intento"), ("POST", "respuesta"), ("GET", "respuesta")]
    cuerpo_get = registros[0]["cuerpo"]
    assert "AGD-1" in cuerpo_get
    assert "PEREZ" not in cuerpo_get and "12.345.678" not in cuerpo_get and "1234 5678" not in cuerpo_get
    assert registros[0]["sha256"]
