"""CLI: configuración mínima, bloqueo de escritura y lectura de booleanos."""
import os

import pytest

from sigah.cli import _booleano, main
from sigah.cliente import CENTRO_ID, URL_BASE


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin .env ni base de auditoría del proyecto
    for variable in [v for v in os.environ if v.startswith("SIGAH_")]:
        monkeypatch.delenv(variable)
    monkeypatch.setenv("SIGAH_API_KEY", "clave")


@pytest.mark.respx(base_url=URL_BASE)
def test_funciona_solo_con_la_api_key(respx_mock):
    ruta = respx_mock.get("/citas").respond(200, json={"estado": "OK", "total": 0, "citas": []})
    assert main(["agenda", "2026-12-15"]) == 0
    assert ruta.calls[0].request.url.params["centro_id"] == str(CENTRO_ID)


def test_sin_api_key(monkeypatch, capsys):
    monkeypatch.delenv("SIGAH_API_KEY")
    assert main(["agenda", "2026-12-15"]) == 2
    assert "SIGAH_API_KEY" in capsys.readouterr().err


@pytest.mark.respx(base_url=URL_BASE)
@pytest.mark.parametrize("ids", ["", "AGD-2,AGD-3"])
def test_escritura_bloqueada_si_el_id_no_esta_listado(monkeypatch, respx_mock, capsys, ids):
    monkeypatch.setenv("SIGAH_IDS_ESCRIBIBLES", ids)
    assert main(["anular", "AGD-1"]) == 2
    assert "escritura bloqueada" in capsys.readouterr().err
    assert not respx_mock.calls


@pytest.mark.respx(base_url=URL_BASE)
def test_dias_llega_al_cliente(respx_mock):
    ruta = respx_mock.get("/citas").respond(200, json={"estado": "OK", "total": 0, "citas": []})
    assert main(["agenda", "2026-12-15", "--dias", "2"]) == 0
    assert ruta.call_count == 3  # días locales 15 y 16 = días SIGAH 15, 16 y 17


@pytest.mark.parametrize("dias", ["0", "-1", "dos", "32", "3000000"])
def test_dias_invalido(capsys, dias):
    with pytest.raises(SystemExit) as salida:
        main(["agenda", "2026-12-15", "--dias", dias])
    assert salida.value.code == 2
    assert "entre 1 y 31" in capsys.readouterr().err


def test_configuracion_invalida(monkeypatch, capsys):
    monkeypatch.setenv("SIGAH_DESFASE_HORAS", "cuatro")
    assert main(["agenda", "2026-12-15"]) == 2
    assert "Configuración inválida" in capsys.readouterr().err


@pytest.mark.parametrize("valor, esperado", [("true", True), ("TRUE", True), ("1", True),
                                             ("false", False), (" False ", False), ("0", False)])
def test_booleano(valor, esperado):
    assert _booleano(valor) is esperado


def test_booleano_invalido_no_se_interpreta_como_false():
    with pytest.raises(ValueError):
        _booleano("si")
