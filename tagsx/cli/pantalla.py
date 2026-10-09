"""Lo común de la terminal: colores, teclas sueltas, cabecera con el logo, firma y un
selector de opciones con ↑/↓, Intro, número o Esc. Sin curses: lo que imprimen las
opciones (inventario, plan) se queda en el historial de la terminal."""
import os
import shutil
import sys

from .. import __version__
from ..text import ACENTO_256, DEGRADADO_256, FOOTER_TEXT, HEADER_ASCII, TENUE_256

_COLORES = {
    "acento": f"38;5;{ACENTO_256}",
    "tenue": f"38;5;{TENUE_256}",
    "negrita": "1",
    "seleccion": f"48;5;{ACENTO_256};38;5;235;1",   # barra de lo elegido
    "rojo": "38;5;203",
    "ambar": "38;5;214",
    "azul": "38;5;75",
}
DEGRADADO = tuple(f"38;5;{c}" for c in DEGRADADO_256)


def hay_color():
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def interactiva():
    return sys.stdin.isatty() and sys.stdout.isatty()


def color(texto, estilo):
    if not hay_color():
        return texto
    return f"\033[{_COLORES.get(estilo, estilo)}m{texto}\033[0m"


def limpiar():
    if interactiva():
        print("\033[H\033[2J\033[3J", end="", flush=True)


# Una pulsación sin esperar a Intro: "izquierda", "derecha", "arriba", "abajo", "intro",
# "borrar", "esc" o el carácter tal cual. Ctrl+C sigue lanzando KeyboardInterrupt.
def leer_tecla():
    if os.name == "nt":
        import msvcrt
        c = msvcrt.getwch()
        if c in ("\x00", "\xe0"):
            return {"K": "izquierda", "M": "derecha", "H": "arriba", "P": "abajo"}.get(msvcrt.getwch(), "")
        if c == "\x03":
            raise KeyboardInterrupt
        return {"\r": "intro", "\x1b": "esc", "\x08": "borrar"}.get(c, c)

    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    antes = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        c = os.read(fd, 1).decode(errors="ignore")
        if c == "\x1b":
            # Una flecha llega como ESC [ C; un Esc suelto no trae nada detrás
            if not select.select([fd], [], [], 0.05)[0]:
                return "esc"
            resto = os.read(fd, 2).decode(errors="ignore")
            return {"[D": "izquierda", "[C": "derecha", "[A": "arriba", "[B": "abajo",
                    "OD": "izquierda", "OC": "derecha", "OA": "arriba", "OB": "abajo"}.get(resto, "")
        return {"\n": "intro", "\r": "intro", "\x7f": "borrar", "\x08": "borrar"}.get(c, c)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, antes)


def separador(caracter="─"):
    return color(caracter * (shutil.get_terminal_size((80, 24)).columns - 1), "tenue")


def cabecera(contexto=""):
    """El logo en degradado y, debajo, de qué cuenta/región se trata."""
    print(separador("═"))
    logo = [l for l in HEADER_ASCII.split("\n") if l.strip()]
    for i, linea in enumerate(logo):
        print(color(linea, DEGRADADO[i % len(DEGRADADO)]))
    pie = f"Etiquetas de AWS · v{__version__}" + (f" · {contexto}" if contexto else "")
    print(color(pie, "tenue"))
    print(separador("═"))


def firma(ayuda="Esc para volver o salir"):
    """La ayuda y la firma, pegadas al fondo de la terminal como en paramsx."""
    if not interactiva():
        return
    columnas, filas = shutil.get_terminal_size((80, 24))
    ancho = columnas - 1
    print(f"\033[{filas - 2};1H" + color(ayuda.center(ancho), "tenue"), end="")
    print(f"\033[{filas - 1};1H" + color("─" * ancho, "tenue"), end="")
    print(f"\033[{filas};1H" + " " * max(0, (ancho - len(FOOTER_TEXT)) // 2) + color(FOOTER_TEXT, "acento"),
          end="", flush=True)


def elegir(titulo, opciones, contexto="", elegida=0, ayuda="↑/↓ para moverte · Intro o número para elegir · Esc para volver"):
    """opciones: lista de (texto, descripción). Devuelve el índice o None (Esc / q)."""
    if not interactiva():
        return _elegir_texto(titulo, opciones, elegida)
    ancho = max(len(f"{i}. {t}") for i, (t, _) in enumerate(opciones, 1)) + 4
    try:
        while True:
            limpiar()
            cabecera(contexto)
            print()
            print(color(titulo, "negrita"))
            print()
            for i, (texto, desc) in enumerate(opciones):
                linea = f"{i + 1}. {texto}"
                if i == elegida:
                    print(color(f" › {linea}".ljust(ancho + 3), "seleccion") + "  " + color(desc, "acento"))
                else:
                    print(f"   {linea}".ljust(ancho + 3) + "  " + color(desc, "tenue"))
            firma(ayuda)
            tecla = leer_tecla()
            if tecla in ("arriba", "izquierda"):
                elegida = (elegida - 1) % len(opciones)
            elif tecla in ("abajo", "derecha"):
                elegida = (elegida + 1) % len(opciones)
            elif tecla.isdigit() and 1 <= int(tecla) <= len(opciones):
                limpiar()
                return int(tecla) - 1
            elif tecla == "intro":
                limpiar()
                return elegida
            elif tecla in ("esc", "q", "Q"):
                limpiar()
                return None
    except KeyboardInterrupt:
        limpiar()
        return None


def _elegir_texto(titulo, opciones, elegida):
    print(titulo)
    for i, (texto, desc) in enumerate(opciones, 1):
        print(f"  {i}. {texto}  ({desc})" if desc else f"  {i}. {texto}")
    try:
        respuesta = input(f"Opción [Intro = {elegida + 1}, q = volver]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not respuesta:
        return elegida
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
        return int(respuesta) - 1
    return None


def pausa():
    """Al acabar una opción: Intro vuelve al menú, Esc sale. Devuelve True para volver."""
    if not interactiva():
        return False
    print()
    print(color("Intro para volver al menú · Esc para salir", "tenue"), end="", flush=True)
    try:
        while True:
            tecla = leer_tecla()
            if tecla == "intro":
                return True
            if tecla in ("esc", "q", "Q"):
                print()
                return False
    except KeyboardInterrupt:
        print()
        return False


def si_o_no(pregunta):
    """Una tecla: 's' es sí; cualquier otra (Esc incluido) es no."""
    if not interactiva():
        try:
            return input(f"{pregunta} [s/N]: ").strip().lower().startswith("s")
        except (EOFError, KeyboardInterrupt):
            return False
    print(f"{pregunta} " + color("[s/N]", "tenue") + " ", end="", flush=True)
    tecla = leer_tecla()
    respuesta = tecla in ("s", "S")
    print("sí" if respuesta else "no")
    return respuesta
