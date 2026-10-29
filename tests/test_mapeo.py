"""Traducción SIGAH → modelo. Datos inventados."""
import logging
from datetime import datetime

from sigah.mapeo import a_cita
from sigah.modelos import ZONA, EstadoCita

REGISTRO = {
    "ID_CITA": "AGD-0000000001", "RUT_PAC": "12.345.678-5", "NOM_PAC": "PEREZ SOTO, JUAN CARLOS",
    "FEC_HORA": "2026-12-15 12:00:00", "COD_EST": 1, "COD_PRO": "MINT",
    "NOM_PRO": "MEDICINA INTERNA", "MEDICO": "DRA. PRUEBA A.", "CENTRO": 3,
    "TEL_PAC": "+56 9 1234 5678", "OBS": None,
}


def test_mapea_registro_completo():
    c = a_cita(REGISTRO, desfase_horas=4)
    assert c.id == "AGD-0000000001"
    assert c.inicio == datetime(2026, 12, 15, 8, 0, tzinfo=ZONA)
    assert c.estado is EstadoCita.AGENDADA
    assert (c.paciente.apellidos, c.paciente.nombres) == ("PEREZ SOTO", "JUAN CARLOS")
    assert c.paciente.rut == "12345678-5"
    assert c.paciente.telefono == "+56912345678"
    assert (c.especialidad, c.centro_id) == ("MINT", 3)


def test_desfase_cruza_al_dia_anterior():
    # 00:30 en SIGAH es 20:30 del día anterior en hora local.
    c = a_cita({**REGISTRO, "FEC_HORA": "2026-10-28 00:30:00"}, desfase_horas=4)
    assert c.inicio == datetime(2026, 10, 27, 20, 30, tzinfo=ZONA)


def test_sin_id_o_fecha_se_descarta(caplog):
    assert a_cita({**REGISTRO, "ID_CITA": None}, 4) is None
    assert a_cita({**REGISTRO, "FEC_HORA": "15/12/2026"}, 4) is None
    assert sum(r.levelno == logging.ERROR for r in caplog.records) == 2


def test_solo_campos_imprescindibles():
    c = a_cita({"ID_CITA": "AGD-1", "FEC_HORA": "2026-12-15 12:00:00"}, 4)
    assert c.estado is EstadoCita.DESCONOCIDO
    assert c.paciente.rut is c.paciente.telefono is c.paciente.nombres is None
    assert c.especialidad is c.profesional is c.centro_id is None


def test_datos_invalidos_quedan_en_none_y_el_log_no_expone_valores(caplog):
    c = a_cita({**REGISTRO, "TEL_PAC": "sin fono", "RUT_PAC": "abc", "COD_EST": 7}, 4)
    assert c.paciente.telefono is None and c.paciente.rut is None
    assert c.estado is EstadoCita.DESCONOCIDO
    assert "sin fono" not in caplog.text and "abc" not in caplog.text


def test_rut_con_dv_invalido_se_conserva_y_se_registra(caplog):
    c = a_cita({**REGISTRO, "RUT_PAC": "12.345.678-9"}, 4)
    assert c.paciente.rut == "12345678-9"
    assert "dígito verificador" in caplog.text


def test_nombre_sin_coma():
    c = a_cita({**REGISTRO, "NOM_PAC": "JUAN PEREZ"}, 4)
    assert (c.paciente.apellidos, c.paciente.nombres) == (None, "JUAN PEREZ")
