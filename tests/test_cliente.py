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
    return SigahClient("clave", 3, url_base=URL, espera=0, **kwargs)


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


def test_clave_desconocida_falla_en_vez_de_devolver_datos_parciales(respx_mock):
    respx_mock.get("/citas").respond(
        200, json={"estado": "OK", "total": 1, "citas": [REGISTRO], "siguiente": "abc"})
    with pytest.raises(RespuestaInesperadaError, match="siguiente"):
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


def test_confirmar_audita_intento_y_respuesta_con_datos_enmascarados(respx_mock):
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle())
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
