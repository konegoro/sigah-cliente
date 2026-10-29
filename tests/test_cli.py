"""Bloqueo de escritura del CLI: solo ids listados en SIGAH_IDS_ESCRIBIBLES."""
import pytest

from sigah.cli import main


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin .env ni base de auditoría del proyecto
    monkeypatch.setenv("SIGAH_API_KEY", "clave")
    monkeypatch.setenv("SIGAH_URL_BASE", "https://sigah.test/api/v1")


@pytest.mark.respx(base_url="https://sigah.test/api/v1")
@pytest.mark.parametrize("ids", ["", "AGD-2,AGD-3"])
def test_escritura_bloqueada_si_el_id_no_esta_listado(monkeypatch, respx_mock, capsys, ids):
    monkeypatch.setenv("SIGAH_IDS_ESCRIBIBLES", ids)
    assert main(["anular", "AGD-1"]) == 2
    assert "escritura bloqueada" in capsys.readouterr().err
    assert not respx_mock.calls
