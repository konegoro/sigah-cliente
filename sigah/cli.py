"""CLI: sigah agenda | cita | confirmar | anular.

Solo SIGAH_API_KEY es obligatoria; el resto de la configuración (.env o variables de entorno) es opcional
y, si falta, rigen los valores por defecto de la librería (ver .env.example).
"""
import argparse
import logging
import os
import sys
from datetime import date, time

from dotenv import find_dotenv, load_dotenv

from .auditoria import Auditoria
from .cliente import CENTRO_ID, MAX_DIAS, SigahClient
from .errores import SigahError
from .modelos import Cita
from .reglas import revisar

ESCRITURAS = ("confirmar", "anular")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))  # el .env de la carpeta desde donde se ejecuta
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    api_key = os.environ.get("SIGAH_API_KEY")
    if not api_key:
        print("Falta SIGAH_API_KEY (ver .env.example)", file=sys.stderr)
        return 2
    # Solo se escribe sobre ids listados explícitamente (ej. las citas de prueba reservadas por Informática).
    escribibles = os.environ.get("SIGAH_IDS_ESCRIBIBLES", "").split(",")
    if args.comando in ESCRITURAS and args.id not in escribibles:
        print(f"{args.id} no está en SIGAH_IDS_ESCRIBIBLES: escritura bloqueada", file=sys.stderr)
        return 2

    try:
        opciones = _desde_env(SIGAH_URL_BASE=("url_base", str), SIGAH_CENTRO_ID=("centro_id", int),
                              SIGAH_DESFASE_HORAS=("desfase_horas", int))
        if getattr(args, "centro", None):
            opciones["centro_id"] = args.centro
        with (Auditoria(**_desde_env(SIGAH_AUDITORIA=("ruta", str))) as auditoria,
              SigahClient(api_key, permitir_escritura=args.comando in ESCRITURAS,
                          auditoria=auditoria, **opciones) as cliente):
            if args.comando == "agenda":
                _agenda(cliente, auditoria, args)
            else:
                operacion = {"cita": cliente.cita, "confirmar": cliente.confirmar, "anular": cliente.anular}
                print(_linea(operacion[args.comando](args.id), args.completo))
    except SigahError as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Configuración inválida: {e}", file=sys.stderr)
        return 2
    return 0


def _agenda(cliente: SigahClient, auditoria: Auditoria, args: argparse.Namespace) -> None:
    citas = cliente.agenda(args.fecha, args.dias)
    for c in citas:
        print(_linea(c, args.completo))
    print(f"{len(citas)} citas")
    reglas = _desde_env(SIGAH_HORA_MIN=("hora_min", time.fromisoformat),
                        SIGAH_HORA_MAX=("hora_max", time.fromisoformat),
                        SIGAH_REVISAR_PROFESIONAL=("revisar_profesional", _booleano))
    alertas = revisar(citas, **reglas)
    auditoria.registrar_alertas(alertas)
    for a in alertas:
        print(f"ALERTA {a.tipo.value}: {', '.join(a.cita_ids)} ({a.detalle})")


def _booleano(valor: str) -> bool:
    """"true"/"false" (o "1"/"0"), sin distinguir mayúsculas. Otro valor es un error, no un `False` silencioso."""
    opciones = {"true": True, "1": True, "false": False, "0": False}
    if valor.strip().lower() not in opciones:
        raise ValueError(f"se esperaba true o false, no {valor!r}")
    return opciones[valor.strip().lower()]


def _dias(valor: str) -> int:
    if not valor.isdecimal() or not 1 <= int(valor) <= MAX_DIAS:
        raise argparse.ArgumentTypeError(f"debe ser un entero entre 1 y {MAX_DIAS}, no {valor!r}")
    return int(valor)


def _desde_env(**variables) -> dict:
    """{parámetro: valor} solo para las variables de entorno definidas; los valores por defecto viven en la librería."""
    return {param: convertir(os.environ[var]) for var, (param, convertir) in variables.items() if os.environ.get(var)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sigah", description="Cliente de la API de agenda SIGAH")
    comunes = argparse.ArgumentParser(add_help=False)
    comunes.add_argument("--completo", action="store_true", help="mostrar datos personales sin enmascarar")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("agenda", parents=[comunes], help="citas de uno o más días (hora local de Chile)")
    p.add_argument("fecha", type=date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--dias", type=_dias, default=1, help=f"cantidad de días desde la fecha (1 a {MAX_DIAS}, por defecto 1)")
    p.add_argument("--centro", type=int, help=f"centro_id (por defecto SIGAH_CENTRO_ID o {CENTRO_ID})")
    for comando, ayuda in [("cita", "una cita por id"),
                           ("confirmar", "confirma una cita (el id debe estar en SIGAH_IDS_ESCRIBIBLES)"),
                           ("anular", "anula una cita (el id debe estar en SIGAH_IDS_ESCRIBIBLES)")]:
        sub.add_parser(comando, parents=[comunes], help=ayuda).add_argument("id")
    return parser


def _linea(c: Cita, completo: bool) -> str:
    p = c.paciente

    def dato(valor):
        if not valor:
            return "-"
        return valor if completo else "***"

    nombre = " ".join(filter(None, [p.nombres, p.apellidos])) or None
    return (f"{c.id}  {c.inicio:%Y-%m-%d %H:%M}  {c.estado.value:<11} {c.especialidad or '-':<5} "
            f"{c.profesional or '-':<18} {dato(nombre)}  {dato(p.rut)}  {dato(p.telefono)}")
