"""Auditoría: lo que se entrega a la plataforma y los eventos de calidad y de reglas. Datos inventados."""
from datetime import date

import httpx
import pytest

from sigah import Alerta, Auditoria, CitaNoEncontradaError, SigahClient, TipoAlerta
from sigah.mapeo import log as log_calidad

URL = "https://sigah.test/api/v1"
pytestmark = pytest.mark.respx(base_url=URL, assert_all_called=False)

# RUT con DV inválido y teléfono incompleto: dos problemas de calidad.
REGISTRO = {"ID_CITA": "AGD-1", "RUT_PAC": "12.345.678-9", "NOM_PAC": "PEREZ, JUAN",
            "FEC_HORA": "2026-12-15 12:00:00", "COD_EST": 1, "CENTRO": 3, "TEL_PAC": "9 1234 567"}


@pytest.fixture
def auditoria():
    with Auditoria(":memory:") as a:
        yield a


def cliente(auditoria, **kwargs):
    return SigahClient("clave", url_base=URL, espera=0, auditoria=auditoria, **kwargs)


def detalle(registro=REGISTRO):
    return httpx.Response(200, json={"estado": "OK", "cita": registro})


def test_problemas_de_calidad_con_codigo_estable_y_sin_datos_personales(respx_mock, auditoria):
    respx_mock.get("/citas/AGD-1").mock(return_value=detalle())
    cliente(auditoria).cita("AGD-1")

    eventos = auditoria.registros("eventos")
    assert {(e["origen"], e["codigo"], e["cita_id"]) for e in eventos} == {
        ("calidad", "rut_dv_invalido", "AGD-1"), ("calidad", "telefono_invalido", "AGD-1")}
    assert not any("12.345.678" in e["detalle"] or "1234 567" in e["detalle"] for e in eventos)
    assert not log_calidad.handlers  # la captura termina con la operación


def test_salida_guarda_nuestra_interpretacion_enmascarada(respx_mock, auditoria):
    def por_fecha(peticion):  # el día local 15 pide los días SIGAH 15 y 16; la cita está solo en el 15
        citas = [REGISTRO] if peticion.url.params["fecha"].startswith("2026-12-15") else []
        return httpx.Response(200, json={"estado": "OK", "total": len(citas), "citas": citas})

    respx_mock.get("/citas").mock(side_effect=por_fecha)
    cliente(auditoria).agenda(date(2026, 12, 15))

    [salida] = auditoria.registros("salidas")
    assert (salida["operacion"], salida["cantidad"], salida["error"]) == ("agenda", 1, None)
    assert '"fecha": "2026-12-15"' in salida["parametros"]
    assert '"inicio": "2026-12-15T08:00:00-03:00"' in salida["resultado"]  # 12:00 en SIGAH = 08:00 local
    assert "12345678" not in salida["resultado"] and "PEREZ" not in salida["resultado"]
    assert salida["sha256"]


def test_salida_guarda_el_error_informado(respx_mock, auditoria):
    respx_mock.get("/citas/AGD-9").respond(200, json={"estado": "ERROR", "codigo": "ERR-04", "msg": "no existe"})
    with pytest.raises(CitaNoEncontradaError):
        cliente(auditoria).cita("AGD-9")

    [salida] = auditoria.registros("salidas")
    assert salida["error"] == "CitaNoEncontradaError: no existe"
    assert salida["resultado"] is None


def test_escritura_registra_una_sola_salida(respx_mock, auditoria):
    # Las relecturas internas (antes y después del POST) no son entregas a la plataforma.
    respx_mock.get("/citas/AGD-1").mock(side_effect=[detalle(), detalle({**REGISTRO, "COD_EST": 2})])
    respx_mock.post("/citas/AGD-1/confirmar").respond(200, text="OK")
    cliente(auditoria, permitir_escritura=True).confirmar("AGD-1")

    assert [s["operacion"] for s in auditoria.registros("salidas")] == ["confirmar"]


def test_alertas_una_fila_por_cita(auditoria):
    auditoria.registrar_alertas([Alerta(TipoAlerta.PACIENTE_MISMA_HORA, ("A", "B"), "mismo paciente, misma hora"),
                                 Alerta(TipoAlerta.SIN_CONTACTO, ("C",), "sin teléfono válido")])

    filas = {(e["codigo"], e["cita_id"], e["relacionadas"]) for e in auditoria.registros("eventos")}
    assert filas == {("paciente_misma_hora", "A", "A,B"), ("paciente_misma_hora", "B", "A,B"),
                     ("sin_contacto", "C", None)}


def test_registros_rechaza_tablas_desconocidas(auditoria):
    with pytest.raises(ValueError):
        auditoria.registros("eventos; DROP TABLE auditoria")
