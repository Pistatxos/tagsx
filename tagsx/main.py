"""Arranque: `tagsx` pregunta Web o Terminal; `tagsx --web` / `tagsx --tui` van directos."""
import os
import shutil
import sys

from . import __version__
from .core import config as core_config
from .cli.pantalla import DEGRADADO as _DEGRADADO
from .cli.pantalla import color as _color
from .cli.pantalla import leer_tecla as _leer_tecla
from .cli.pantalla import limpiar as _limpiar
from .text import FOOTER_TEXT, HEADER_ASCII

def version_actual():
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("tagsx")
        except PackageNotFoundError:
            return f"{__version__} (desde el código fuente, sin instalar)"
    except ImportError:
        return __version__


def show_help():
    print(f"""
TagsX {version_actual()} - Etiquetas de AWS: inventario, edición y aplicar

Comandos:
  tagsx                 Pregunta si quieres la versión web o la de terminal.
  tagsx --web           Abre la versión web en el navegador.
  tagsx --tui           Abre el menú de terminal.
  tagsx configure       Crea {core_config.CONFIG_PATH} si no existe y lo valida.
  tagsx --version       Muestra la versión instalada.
  tagsx --help          Muestra esta ayuda.

Menú de terminal (tagsx --tui):
  1. Inventario                 Lee AWS y genera exports/aws_inventory_<fecha>.xlsx y .csv
  2. Cargar y aplicar           Lee aws_inventory.xlsx (o .csv) de este directorio, enseña
                                el plan y aplica tras escribir APLICAR.
  3. Detectar servicios activos Propone los 'servicios' predeterminados según el inventario.
  ↑/↓ para moverte, Intro o el número para elegir, Esc para volver o salir.

Reglas del fichero:
  - nombre, id, servicio, region, arn, url: informativas, nunca se tocan.
  - Columnas del esquema: vacía = no se toca; con valor (también 'none') = crea o cambia.
  - Cualquier otra columna: vacía = se BORRA esa etiqueta; con valor = crea o cambia.

Variables de entorno: AWS_REGIONS (regiones separadas por coma), OUT_DIR (carpeta de
exportación, 'exports' por defecto), AWS_PROFILE si 'perfil_aws' está vacío.

Más en https://github.com/Pistatxos/tagsx
""")


def configurar():
    if core_config.crear_si_no_existe():
        print(f"Creado {core_config.CONFIG_PATH} con cada opción comentada.")
        print("Ajusta el perfil de AWS, las regiones y el esquema (o hazlo desde la web, en Ajustes).")
        return
    print(f"Ya existe {core_config.CONFIG_PATH}: no se toca.")
    revisar_config()


def revisar_config():
    try:
        config = core_config.cargar()
    except Exception as e:
        print(f"Error al leer {core_config.CONFIG_PATH}: {e}")
        return None
    errores, avisos = core_config.validar(config)
    for aviso in avisos:
        print(f"Aviso: {aviso}")
    if errores:
        print(f"\nErrores en {core_config.CONFIG_PATH}:\n")
        for error in errores:
            print(f"  - {error}")
        return None
    return config


# ---------------------------------------------------------------- portada Web / Terminal
# Menú de arranque: web o terminal. Devuelve "web", "tui" o None (salir). En una terminal
# se elige con ← →, Intro o el número; sin terminal (tubería), con input().

def elegir_modo():
    elegida = "1"
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _elegir_modo_texto(elegida)

    try:
        while True:
            _limpiar()
            print(portada(elegida))
            print("  " + _color("← → para elegir · Intro para abrir · Esc para salir", "tenue"))
            tecla = _leer_tecla()
            if tecla in ("izquierda", "arriba"):
                elegida = "1"
            elif tecla in ("derecha", "abajo"):
                elegida = "2"
            elif tecla in ("1", "2"):
                elegida = tecla
                tecla = "intro"
            elif tecla in ("q", "Q", "esc"):
                _limpiar()
                return None
            if tecla == "intro":
                _limpiar()
                return "web" if elegida == "1" else "tui"
    except KeyboardInterrupt:
        _limpiar()
        return None


def _elegir_modo_texto(defecto):
    print(portada(defecto))
    while True:
        try:
            opcion = input(f"  › Elige 1 o 2 [Intro = {defecto}]: ").strip() or defecto
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if opcion == "1":
            return "web"
        if opcion == "2":
            return "tui"
        if opcion.lower() in ("q", "salir"):
            return None


# Las dos tarjetas, lado a lado. La elegida va en color. Se componen en texto plano y
# luego se colorean línea a línea, para que los códigos ANSI no descuadren el ancho.
def _tarjetas(defecto):
    ancho = 30
    web = [
        "1 · WEB",
        "",
        "┌──────────────────────┐",
        "│ ● ● ●   127.0.0.1    │",
        "│ Name  Env    Owner   │",
        "│ ▤▤▤▤  prod   ▤▤▤▤    │",
        "└──────────────────────┘",
        "Editar en el navegador",
    ]
    tui = [
        "2 · TERMINAL",
        "",
        "┌──────────────────────┐",
        "│ $ tagsx              │",
        "│ > 1. Inventario      │",
        "│   2. Cargar y aplicar│",
        "└──────────────────────┘",
        "Exportar y usar Excel",
    ]

    def caja(lineas, opcion):
        estilo = "acento" if opcion == defecto else "tenue"

        def borde(t):
            return _color(t, estilo)

        filas = [borde("╭" + "─" * ancho + "╮")]
        for i, linea in enumerate(lineas):
            texto = f"  {linea}".ljust(ancho)
            if i == 0:
                texto = _color(texto, "negrita") if estilo == "acento" else texto
            elif i == len(lineas) - 1:
                texto = _color(texto, "tenue")
            filas.append(borde("│") + texto + borde("│"))
        filas.append(borde("╰" + "─" * ancho + "╯"))
        return filas

    return [f"  {a}  {b}" for a, b in zip(caja(web, "1"), caja(tui, "2"))]


def portada(defecto):
    columnas = shutil.get_terminal_size((80, 24)).columns
    if columnas < 70:
        lineas = [f"TagsX {__version__} · {FOOTER_TEXT}",
                  "  1. Web       (editar en el navegador)",
                  "  2. Terminal  (exportar y usar Excel)"]
        return "\n".join(lineas)

    logo = [l for l in HEADER_ASCII.split("\n") if l.strip()]
    lineas = [""]
    for i, linea in enumerate(logo):
        lineas.append("  " + _color(linea, _DEGRADADO[i % len(_DEGRADADO)]))
    lineas.append("  " + _color(f"Etiquetas de AWS · v{__version__} · ", "tenue") + _color(FOOTER_TEXT, "acento"))
    lineas.append("")
    lineas.extend(_tarjetas(defecto))
    lineas.append("")
    return "\n".join(lineas)


def arrancar_web():
    from .web.app import arrancar
    arrancar(abrir_navegador="--sin-navegador" not in sys.argv[1:])


def entry_point():
    argumentos = sys.argv[1:]
    if argumentos:
        command = argumentos[0]
        if command in ("configure", "config", "configurar"):
            configurar()
            return
        if command in ("--help", "-h", "help"):
            show_help()
            return
        if command in ("--version", "-v", "version"):
            print(f"tagsx {version_actual()}")
            return

    if "--web" in argumentos:
        modo = "web"
    elif "--tui" in argumentos:
        modo = "tui"
    else:
        modo = elegir_modo()
    if modo is None:
        return
    if modo == "web":
        # La web no necesita la configuración previa: se hace desde Ajustes
        arrancar_web()
        return

    if not os.path.exists(core_config.CONFIG_PATH):
        print(f"Aún no hay configuración ({core_config.CONFIG_PATH}): se usa la de ejemplo.")
        print("Créala con 'tagsx configure' (o desde la web, en Ajustes).\n")
    config = revisar_config()
    if config is None:
        return
    from .cli.menu import main
    main(config)


if __name__ == "__main__":
    entry_point()
