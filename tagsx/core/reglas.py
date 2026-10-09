"""Reglas de las etiquetas: límites de AWS, prefijos reservados, minúsculas y catálogos."""

# Límites de la Tagging API (y de casi todos los servicios)
MAX_ETIQUETAS = 50
MAX_CLAVE = 128
MAX_VALOR = 256

# Las de AWS (aws:cloudformation:stack-name...) no se pueden tocar y las de Kubernetes
# las gestiona el propio clúster: ni se muestran ni se aplican.
PREFIJOS_RESERVADOS = ("aws:", "kubernetes.io/")

# Lo que se considera «sin valor a propósito» en una celda (ver README: none ≠ vacío)
NONE = "none"

# Excel (locale español) muestra las celdas con true/false como VERDADERO/FALSO
# y, al guardar como .csv, escribe ese texto localizado en vez del valor
# original. Sin esto, un tag como PatchEnabled ('true'/'false', usado por SSM
# Patch Manager/DLM) se sobreescribiria con 'VERDADERO'/'FALSO', que AWS no reconoce.
BOOLEAN_ALIASES = {
    "true": "true", "false": "false",
    "verdadero": "true", "falso": "false",
}


def normalize_boolean_like(value):
    return BOOLEAN_ALIASES.get(value.strip().lower(), value)


def clave_reservada(clave):
    return clave.lower().startswith("aws:") or clave.startswith("kubernetes.io/")


def etiquetas_visibles(tags):
    """{clave: valor} sin las reservadas, desde la lista [{Key, Value}] de AWS."""
    return {t["Key"]: t["Value"] for t in tags or [] if not clave_reservada(t["Key"])}


def minuscula_obligada(clave, config):
    return bool(config.get("minusculas")) and clave in config.get("esquema", []) and clave != "Name"


def normalize(clave, valor, config):
    """Lo que la terminal aplica: los valores del esquema en minúscula (salvo Name)."""
    return valor.lower() if minuscula_obligada(clave, config) else valor


def errores_etiqueta(clave, valor):
    """Lo que AWS rechazaría: se marca como error y ese recurso no se aplica."""
    errores = []
    if not clave.strip():
        errores.append("Hay una etiqueta sin nombre.")
    if clave_reservada(clave):
        errores.append(f"{clave}: los prefijos aws: y kubernetes.io/ están reservados.")
    if len(clave) > MAX_CLAVE:
        errores.append(f"{clave[:40]}…: la clave pasa de {MAX_CLAVE} caracteres.")
    if valor is not None and len(valor) > MAX_VALOR:
        errores.append(f"{clave}: el valor pasa de {MAX_VALOR} caracteres ({len(valor)}).")
    return errores


def avisos_valor(clave, valor, config):
    """Avisos que no bloquean: mayúsculas donde se esperan minúsculas, o un valor fuera
    del catálogo conocido."""
    avisos = []
    if not valor:
        return avisos
    if minuscula_obligada(clave, config) and valor != valor.lower():
        avisos.append(f"{clave}: '{valor}' lleva mayúsculas.")
    catalogo = (config.get("catalogos") or {}).get(clave)
    if catalogo and valor not in catalogo and valor.lower() != NONE:
        avisos.append(f"{clave}: '{valor}' no está en el catálogo ({', '.join(catalogo)}).")
    return avisos
