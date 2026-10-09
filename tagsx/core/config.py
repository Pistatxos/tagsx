"""La configuración (~/.xsoft/tagsx_config.py): leerla como datos, validarla y guardarla.

Ni la terminal ni la web ejecutan el fichero: se leen sus asignaciones literales con
`ast`. Al guardar se sustituyen solo esas asignaciones, así los comentarios se quedan.
"""
import ast
import json
import os

from .reglas import clave_reservada, MAX_CLAVE
from .scanners import SERVICIOS_DETECTABLES

CONFIG_PATH = os.path.expanduser("~/.xsoft/tagsx_config.py")
# Instantánea del último inventario e historial de lo aplicado
DATA_DIR = os.path.expanduser("~/.xsoft/tagsx")

PLANTILLA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tagsx_config.py"
)

CLAVES = ("perfil_aws", "regiones", "servicios", "esquema", "catalogos", "minusculas")


class ConfigNoLegible(ValueError):
    """El fichero tiene algo que no es un literal y no se puede leer sin ejecutarlo."""


def leer_asignaciones(texto):
    try:
        arbol = ast.parse(texto or "")
    except SyntaxError as e:
        raise ConfigNoLegible(f"Error de sintaxis en la línea {e.lineno}: {e.msg}.") from None

    valores, no_literales = {}, []
    for nodo in arbol.body:
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name)):
            nombre = nodo.targets[0].id
            try:
                valores[nombre] = ast.literal_eval(nodo.value)
            except ValueError:
                no_literales.append(nombre)
    return valores, no_literales


def config_plantilla():
    with open(PLANTILLA_PATH, "r", encoding="utf-8") as f:
        valores, _ = leer_asignaciones(f.read())
    return {k: valores[k] for k in CLAVES}


def config_desde_valores(valores):
    """La config con lo que falte relleno desde la plantilla."""
    config = config_plantilla()
    for clave in CLAVES:
        if clave in valores:
            config[clave] = valores[clave]
    return config


def cargar(path=None):
    """La config del fichero o, si no existe, la de la plantilla."""
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        return config_plantilla()
    with open(path, "r", encoding="utf-8") as f:
        valores, no_literales = leer_asignaciones(f.read())
    problemas = [n for n in no_literales if n in CLAVES]
    if problemas:
        raise ConfigNoLegible(
            f"{', '.join(problemas)} no se puede leer como datos (usa variables, imports o "
            "llamadas). Déjalo con valores literales."
        )
    return config_desde_valores(valores)


def regiones_efectivas(config):
    """Las regiones a escanear: AWS_REGIONS (separadas por coma) manda sobre la config."""
    entorno = os.getenv("AWS_REGIONS", "")
    regiones = entorno.split(",") if entorno.strip() else config.get("regiones") or []
    return [r.strip() for r in regiones if str(r).strip()]


def validar(config):
    """(errores, avisos) de una config."""
    errores, avisos = [], []

    if not isinstance(config.get("perfil_aws"), str):
        errores.append("'perfil_aws' debe ser un texto (\"\" para el perfil por defecto).")

    regiones = config.get("regiones")
    if not isinstance(regiones, list) or not [r for r in regiones if str(r).strip()]:
        errores.append("'regiones' debe ser una lista con al menos una región.")

    servicios = config.get("servicios")
    if not isinstance(servicios, list):
        errores.append("'servicios' debe ser una lista.")
    else:
        desconocidos = [s for s in servicios if s not in SERVICIOS_DETECTABLES]
        if desconocidos:
            avisos.append(f"Servicios sin escáner (se ignoran): {', '.join(map(str, desconocidos))}.")

    esquema = config.get("esquema")
    if not isinstance(esquema, list) or not esquema:
        errores.append("'esquema' debe ser una lista con al menos una etiqueta.")
        esquema = []
    vistos = set()
    for clave in esquema:
        if not isinstance(clave, str) or not clave.strip():
            errores.append(f"Etiqueta vacía o no válida en 'esquema': {clave!r}.")
            continue
        if clave in vistos:
            errores.append(f"La etiqueta {clave!r} está repetida en 'esquema'.")
        vistos.add(clave)
        if clave_reservada(clave):
            errores.append(f"{clave!r} empieza por un prefijo reservado (aws:, kubernetes.io/).")
        if len(clave) > MAX_CLAVE:
            errores.append(f"{clave!r} pasa de {MAX_CLAVE} caracteres.")

    catalogos = config.get("catalogos")
    if not isinstance(catalogos, dict):
        errores.append("'catalogos' debe ser un diccionario {etiqueta: [valores]}.")
    else:
        for clave, valores in catalogos.items():
            if not isinstance(valores, list) or not all(isinstance(v, str) for v in valores):
                errores.append(f"El catálogo de {clave!r} debe ser una lista de textos.")
            if clave not in vistos:
                avisos.append(f"Hay catálogo para {clave!r}, que no está en el esquema.")

    if not isinstance(config.get("minusculas"), bool):
        errores.append("'minusculas' debe ser True o False.")

    return errores, avisos


# ---------------------------------------------------------------------------------------
# Escribir
# ---------------------------------------------------------------------------------------

def _literal(valor):
    if isinstance(valor, str):
        return json.dumps(valor, ensure_ascii=False)
    if isinstance(valor, bool) or valor is None:
        return repr(valor)
    if isinstance(valor, (int, float)):
        return repr(valor)
    if isinstance(valor, (list, tuple)):
        return "[" + ", ".join(_literal(v) for v in valor) + "]"
    if isinstance(valor, dict):
        return "{" + ", ".join(f"{_literal(k)}: {_literal(v)}" for k, v in valor.items()) + "}"
    raise TypeError(f"No se puede escribir {type(valor).__name__} en la configuración.")


def _bloque(nombre, valor):
    """Una asignación legible: las listas, un elemento por línea; los dicts, una clave."""
    if isinstance(valor, list) and valor:
        return "\n".join([f"{nombre} = ["] + [f"    {_literal(v)}," for v in valor] + ["]"])
    if isinstance(valor, dict) and valor:
        return "\n".join([f"{nombre} = {{"] + [f"    {_literal(k)}: {_literal(v)},"
                                              for k, v in valor.items()] + ["}"])
    return f"{nombre} = {_literal(valor)}"


def texto_config(config, texto_actual):
    """El fichero con las asignaciones de CLAVES sustituidas; el resto, intacto."""
    arbol = ast.parse(texto_actual)
    lineas = texto_actual.splitlines(keepends=True)
    tramos = []
    for nodo in arbol.body:
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name) and nodo.targets[0].id in CLAVES):
            tramos.append((nodo.lineno, nodo.end_lineno, nodo.end_col_offset, nodo.targets[0].id))

    escritos = set()
    for inicio, fin, col_fin, nombre in sorted(tramos, reverse=True):
        # Un comentario detrás de la asignación, en su última línea, se conserva
        resto = lineas[fin - 1].encode("utf-8")[col_fin:].decode("utf-8").rstrip("\n")
        cola = f"  {resto.strip()}" if resto.strip().startswith("#") else ""
        sustituto = "" if nombre in escritos else _bloque(nombre, config[nombre]) + cola + "\n"
        escritos.add(nombre)
        lineas[inicio - 1:fin] = [sustituto]

    texto = "".join(lineas)
    faltan = [n for n in CLAVES if n not in escritos]
    if faltan:
        texto = texto.rstrip("\n") + "\n\n## Añadido por tagsx\n"
        texto += "\n".join(_bloque(n, config[n]) for n in faltan) + "\n"
    return texto


def guardar(config, path=None):
    """Guarda la config. Antes comprueba que lo escrito se relee igual; el fichero
    anterior queda como .bak."""
    path = path or CONFIG_PATH
    errores, _ = validar(config)
    if errores:
        raise ValueError("La configuración tiene errores: " + " ".join(errores))
    origen = path if os.path.exists(path) else PLANTILLA_PATH
    with open(origen, "r", encoding="utf-8") as f:
        actual = f.read()

    texto = texto_config(config, actual)
    valores, _ = leer_asignaciones(texto)
    for clave in CLAVES:
        if valores.get(clave) != config[clave]:
            raise ValueError(f"No se ha guardado: '{clave}' no se releía igual.")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path + ".bak", "w", encoding="utf-8") as f:
            f.write(actual)
    temporal = path + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(temporal, path)
    return texto


def crear_si_no_existe(path=None):
    """Copia la plantilla comentada. Devuelve True si la ha creado."""
    path = path or CONFIG_PATH
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(PLANTILLA_PATH, "r", encoding="utf-8") as f:
        texto = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(texto)
    return True
