"""Reglas de negocio sobre la agenda. Datos inventados."""
from datetime import datetime

from sigah.modelos import ZONA, Cita, EstadoCita, Paciente
from sigah.reglas import TipoAlerta, revisar

AHORA = datetime(2026, 12, 1, tzinfo=ZONA)


def cita(id_, hora=10, rut="11111111-1", especialidad="MINT", profesional="DR. A", telefono="+56911111111",
         estado=EstadoCita.AGENDADA):
    return Cita(id_, datetime(2026, 12, 15, hora, tzinfo=ZONA), estado,
                Paciente(rut=rut, telefono=telefono), especialidad=especialidad, profesional=profesional)


def tipos(alertas):
    return {(a.tipo, a.cita_ids) for a in alertas}


def test_agenda_limpia_sin_alertas():
    assert revisar([cita("A"), cita("B", hora=11, rut="2-7", especialidad="CARD")], ahora=AHORA) == []


def test_paciente_con_dos_citas_a_la_misma_hora():
    alertas = revisar([cita("A"), cita("B", especialidad="CARD", profesional="DR. B")], ahora=AHORA)
    assert tipos(alertas) == {(TipoAlerta.PACIENTE_MISMA_HORA, ("A", "B"))}


def test_paciente_con_misma_especialidad_el_mismo_dia():
    alertas = revisar([cita("A"), cita("B", hora=15)], ahora=AHORA)
    assert tipos(alertas) == {(TipoAlerta.PACIENTE_MISMA_ESPECIALIDAD_DIA, ("A", "B"))}


def test_profesional_con_dos_pacientes_solo_si_se_activa_y_no_para_equipos():
    citas = [cita("A"), cita("B", rut="2-7", especialidad="CARD"),
             cita("C", hora=20, rut="4-3", profesional="EQUIPO TURNO 3"),
             cita("D", hora=20, rut="3-5", profesional="EQUIPO TURNO 3")]
    assert revisar(citas, ahora=AHORA) == []
    assert tipos(revisar(citas, revisar_profesional=True, ahora=AHORA)) == {
        (TipoAlerta.PROFESIONAL_MISMA_HORA, ("A", "B"))}


def test_alertas_individuales():
    alertas = revisar([cita("SIN_FONO", telefono=None), cita("RARA", rut="2-7", estado=EstadoCita.DESCONOCIDO),
                       cita("MADRUGADA", hora=3, rut="3-5")], ahora=AHORA)
    assert tipos(alertas) == {(TipoAlerta.SIN_CONTACTO, ("SIN_FONO",)),
                              (TipoAlerta.ESTADO_DESCONOCIDO, ("RARA",)),
                              (TipoAlerta.HORARIO_FUERA_DE_RANGO, ("MADRUGADA",))}


def test_cita_pasada():
    alertas = revisar([cita("A")], ahora=datetime(2026, 12, 16, tzinfo=ZONA))
    assert tipos(alertas) == {(TipoAlerta.CITA_PASADA, ("A",))}
