"""CLI: sigah agenda | cita | confirmar | anular. Configuración por variables de entorno o `.env`."""
import argparse
import logging
import os
import sys
from datetime import date, time

from dotenv import load_dotenv

from .auditoria import Auditoria
from .cliente import SigahClient
from .errores import SigahError
from .modelos import Cita
from .reglas import revisar

CENTRO_POR_DEFECTO = 3  # Hospital, según Informática
ESCRITURAS = ("confirmar", "anular")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
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

    centro_id = getattr(args, "centro", None) or int(os.environ.get("SIGAH_CENTRO_ID", CENTRO_POR_DEFECTO))
    opciones = _desde_env(SIGAH_URL_BASE=("url_base", str), SIGAH_DESFASE_HORAS=("desfase_horas", int))
    with (Auditoria(**_desde_env(SIGAH_AUDITORIA=("ruta", str))) as auditoria,
          SigahClient(api_key, centro_id, permitir_escritura=args.comando in ESCRITURAS,
                      auditoria=auditoria, **opciones) as cliente):
        try:
            if args.comando == "agenda":
                _agenda(cliente, args)
            else:
                operacion = {"cita": cliente.cita, "confirmar": cliente.confirmar, "anular": cliente.anular}
                print(_linea(operacion[args.comando](args.id), args.completo))
        except SigahError as e:
            print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    return 0


def _agenda(cliente: SigahClient, args: argparse.Namespace) -> None:
    citas = cliente.agenda(args.fecha)
    for c in citas:
        print(_linea(c, args.completo))
    print(f"{len(citas)} citas")
    reglas = _desde_env(SIGAH_HORA_MIN=("hora_min", time.fromisoformat),
                        SIGAH_HORA_MAX=("hora_max", time.fromisoformat),
                        SIGAH_REVISAR_PROFESIONAL=("revisar_profesional", lambda v: v == "1"))
    for a in revisar(citas, **reglas):
        print(f"ALERTA {a.tipo.value}: {', '.join(a.cita_ids)} ({a.detalle})")


def _desde_env(**variables) -> dict:
    """{parámetro: valor} solo para las variables de entorno definidas; los valores por defecto viven en la librería."""
    return {param: convertir(os.environ[var]) for var, (param, convertir) in variables.items() if os.environ.get(var)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sigah", description="Cliente de la API de agenda SIGAH")
    comunes = argparse.ArgumentParser(add_help=False)
    comunes.add_argument("--completo", action="store_true", help="mostrar datos personales sin enmascarar")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("agenda", parents=[comunes], help="citas de un día (hora local de Chile)")
    p.add_argument("fecha", type=date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--centro", type=int, help=f"centro_id (por defecto SIGAH_CENTRO_ID o {CENTRO_POR_DEFECTO})")
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
