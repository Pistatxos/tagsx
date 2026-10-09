"""Lo que tagsx guarda en ~/.xsoft/tagsx/: la instantánea del último inventario (para abrir
la web al momento) y el historial de lo aplicado (para saber qué se hizo y deshacerlo).

Las etiquetas no son secretos, pero son de tu cuenta: los ficheros se crean solo para tu
usuario (0600)."""
import json
import os
import secrets
from datetime import datetime

from .config import DATA_DIR


def _ruta(nombre, data_dir=None):
    return os.path.join(data_dir or DATA_DIR, nombre)


def _escribir(path, texto, modo="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if modo == "a" else os.O_TRUNC), 0o600)
    with os.fdopen(fd, modo, encoding="utf-8") as f:
        f.write(texto)


# ---------------------------------------------------------------------------- instantánea

def guardar_snapshot(datos, data_dir=None):
    path = _ruta("snapshot.json", data_dir)
    temporal = path + ".tmp"
    _escribir(temporal, json.dumps(datos, ensure_ascii=False))
    os.replace(temporal, path)


def leer_snapshot(data_dir=None):
    try:
        with open(_ruta("snapshot.json", data_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def actualizar_snapshot(resultados, data_dir=None):
    """Tras aplicar, la instantánea refleja lo que AWS aceptó (sin volver a leerlo todo)."""
    datos = leer_snapshot(data_dir)
    if not datos:
        return None
    por_arn = {r["arn"]: r for r in datos["recursos"]}
    for res in resultados:
        r = por_arn.get(res["arn"])
        if not r:
            continue
        for clave, valor in res["despues"].items():
            if valor is None:
                r["tags"].pop(clave, None)
            else:
                r["tags"][clave] = valor
                if clave not in datos["claves"]:
                    datos["claves"].append(clave)
            if clave == "Name":
                r["nombre"] = valor or r["id"].rstrip("/").split("/")[-1]
    guardar_snapshot(datos, data_dir)
    return datos


# ---------------------------------------------------------------------------- historial

def registrar_lote(resultados, cuenta, perfil="", origen="web", deshace=None, data_dir=None):
    """Un lote por cada «aplicar»: {arn, antes, después} de las claves que se tocaron de
    verdad. Devuelve el lote (o None si no se aplicó nada)."""
    cambios = [{"arn": r["arn"], "region": r["region"], "antes": r["antes"], "despues": r["despues"]}
               for r in resultados if r["despues"]]
    errores = [{"arn": r["arn"], "errores": r["errores"]} for r in resultados if r["errores"]]
    if not cambios and not errores:
        return None
    ahora = datetime.now()
    lote = {
        "id": ahora.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2),
        "fecha": ahora.isoformat(timespec="seconds"),
        "cuenta": cuenta,
        "perfil": perfil or "",
        "origen": origen,
        "deshace": deshace,
        "cambios": cambios,
        "errores": errores,
    }
    _escribir(_ruta("historial.jsonl", data_dir), json.dumps(lote, ensure_ascii=False) + "\n", "a")
    return lote


def lotes(data_dir=None):
    """Todos los lotes, el más reciente primero. Una línea rota no tira el resto."""
    try:
        with open(_ruta("historial.jsonl", data_dir), "r", encoding="utf-8") as f:
            lineas = f.readlines()
    except OSError:
        return []
    resultado = []
    for linea in lineas:
        try:
            resultado.append(json.loads(linea))
        except ValueError:
            continue
    return resultado[::-1]


def lote(id_lote, data_dir=None):
    return next((l for l in lotes(data_dir) if l["id"] == id_lote), None)


def items_deshacer(un_lote):
    """Los cambios que deshacen un lote, en el formato de planificar: volver a «antes»,
    esperando encontrar «después» (si alguien lo cambió desde entonces, es un conflicto)."""
    return [{"arn": c["arn"], "cambios": dict(c["antes"]), "base": dict(c["despues"])}
            for c in un_lote["cambios"]]
