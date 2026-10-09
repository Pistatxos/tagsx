"""El plan: qué etiquetas se crean, cambian o borran en cada recurso, antes de tocar AWS.

Dos entradas, un mismo resultado (`operaciones`):

- build_row_plan: una fila del CSV/XLSX con sus reglas (esquema vacío = no se toca,
  otra columna vacía = se borra, `none` es un valor). Lo usan la terminal y «Importar».
- planificar: los cambios de la web ({clave: valor | None}) contra lo que hay AWS ahora
  y lo que había cuando se leyó: si alguien la cambió entretanto, es un conflicto y esa
  etiqueta no se toca.
"""
from .inventario import INFO_COLUMNS
from .reglas import (
    MAX_ETIQUETAS, avisos_valor, clave_reservada, errores_etiqueta, normalize,
    normalize_boolean_like,
)


def columnas_dinamicas(fieldnames, esquema):
    """(columnas de etiquetas ajenas al esquema, avisos). Se descartan las cabeceras en
    blanco (columna vacía o corrupta al editar en Excel), «asociados» (informativa, del
    antiguo inventario «sugerido») y las de prefijo reservado, avisando."""
    columnas, avisos = [], []
    for c in fieldnames:
        if not c.strip() or c in INFO_COLUMNS or c in esquema or c == "asociados":
            continue
        if clave_reservada(c):
            avisos.append(f"La columna '{c}' usa un prefijo reservado (aws:, kubernetes.io/): se ignora.")
            continue
        columnas.append(c)
    return columnas, avisos


def _limite(current_tags, poner, quitar):
    total = len(set(current_tags) | set(poner)) - len([k for k in quitar if k in current_tags])
    if total > MAX_ETIQUETAS:
        return [f"Quedaría con {total} etiquetas: AWS admite {MAX_ETIQUETAS} por recurso."]
    return []


def build_row_plan(arn, csv_row, current_tags, dynamic_columns, config):
    tags_to_apply = {}
    keys_to_remove = []
    notes = []
    errores = []

    for key in config["esquema"]:
        cell = normalize_boolean_like(csv_row.get(key) or "")
        if not cell.strip():
            continue
        new_value = normalize(key, cell, config)
        current_value = current_tags.get(key)
        notes.extend(f"AVISO: {a}" for a in avisos_valor(key, new_value, config))
        if current_value != new_value:
            tags_to_apply[key] = new_value
            action = "crear" if key not in current_tags else "actualizar"
            notes.append(f"{action} {key}: {current_value!r} -> {new_value!r}")

    for key in dynamic_columns:
        cell = normalize_boolean_like(csv_row.get(key) or "")
        current_value = current_tags.get(key)
        if cell.strip():
            if current_value != cell:
                tags_to_apply[key] = cell
                action = "crear" if key not in current_tags else "actualizar"
                notes.append(f"{action} {key}: {current_value!r} -> {cell!r}")
        else:
            if current_value is not None:
                keys_to_remove.append(key)
                notes.append(
                    f"borrar {key} (tag ajena al esquema, celda vacia): {current_value!r} -> (eliminada)"
                )

    if not tags_to_apply and not keys_to_remove:
        return None

    for key, value in tags_to_apply.items():
        errores.extend(errores_etiqueta(key, value))
    errores.extend(_limite(current_tags, tags_to_apply, keys_to_remove))
    notes.extend(f"ERROR: {e}" for e in errores)

    return {
        "arn": arn,
        "status": "error" if errores else "planned",
        "apply_tags": tags_to_apply,
        "remove_keys": keys_to_remove,
        "antes": {k: current_tags.get(k) for k in list(tags_to_apply) + keys_to_remove},
        "errores": errores,
        "notes": "; ".join(notes),
        "notes_list": notes,
        "applied": False,
    }


def cambios_desde_filas(fieldnames, filas, recursos_por_arn, config):
    """«Importar» de la web: las filas del CSV/XLSX como cambios {arn: {clave: valor|None}}
    respecto a la instantánea, con las mismas reglas que la terminal."""
    from .arn import normalizar_arn

    dinamicas, avisos = columnas_dinamicas(fieldnames, config["esquema"])
    cambios, desconocidos = {}, 0
    for fila in filas:
        arn = normalizar_arn(fila.get("arn") or "")
        if not arn:
            continue
        r = recursos_por_arn.get(arn)
        if r is None:
            desconocidos += 1
            continue
        plan = build_row_plan(arn, fila, r["tags"], dinamicas, config)
        if plan:
            c = {k: v for k, v in plan["apply_tags"].items()}
            c.update({k: None for k in plan["remove_keys"]})
            cambios[arn] = c
    if desconocidos:
        avisos.append(f"{desconocidos} fila(s) con un ARN que no está en el inventario: "
                      "se ignoran (vuelve a leer de AWS si son nuevos).")
    return cambios, avisos


def planificar(items, actuales, config, regiones, omitidos=None):
    """El plan de la web. `items`: [{arn, cambios: {clave: valor|None}, base: {clave: valor
    leído|None}}]; `actuales`: {arn: etiquetas de AWS ahora}; `regiones`: {arn: región}.

    Por recurso devuelve crear/cambiar/borrar, los conflictos (la etiqueta cambió en AWS
    desde que se leyó: no se toca), los errores (no se aplica nada de ese recurso) y los
    avisos (no bloquean)."""
    omitidos = omitidos or {}
    plan = []
    for it in items:
        arn = it["arn"]
        base = it.get("base") or {}
        act = actuales.get(arn, {})
        p = {"arn": arn, "region": regiones.get(arn), "nombre": it.get("nombre") or "",
             "crear": {}, "cambiar": {}, "borrar": {}, "conflictos": [], "errores": [],
             "avisos": [], "sin_cambio": []}
        if not p["region"]:
            p["errores"].append("No se sabe en qué región está: no se toca.")
        if arn in omitidos:
            p["errores"].append(omitidos[arn])

        for clave, nuevo in (it.get("cambios") or {}).items():
            nuevo = None if nuevo is None or str(nuevo) == "" else str(nuevo)
            ahora = act.get(clave)
            if ahora == nuevo:
                p["sin_cambio"].append(clave)
                continue
            if clave in base and base[clave] != ahora:
                p["conflictos"].append({"clave": clave, "leido": base[clave], "ahora": ahora, "nuevo": nuevo})
                continue
            if nuevo is None:
                p["borrar"][clave] = ahora
            elif ahora is None:
                p["crear"][clave] = nuevo
            else:
                p["cambiar"][clave] = [ahora, nuevo]
            p["errores"].extend(errores_etiqueta(clave, nuevo))
            p["avisos"].extend(avisos_valor(clave, nuevo, config) if nuevo else [])

        poner = {**p["crear"], **{k: v[1] for k, v in p["cambiar"].items()}}
        if poner or p["borrar"]:
            p["errores"].extend(_limite(act, poner, list(p["borrar"])))
        hay_cambios = bool(poner or p["borrar"])
        p["estado"] = ("error" if p["errores"] and (hay_cambios or arn in omitidos)
                       else "ok" if hay_cambios else "conflicto" if p["conflictos"] else "nada")
        p["antes"] = {k: act.get(k) for k in list(poner) + list(p["borrar"])}
        plan.append(p)
    return plan


def operaciones(plan):
    """Lo que de verdad se manda a AWS: solo los recursos sin errores y con cambios."""
    ops = []
    for p in plan:
        if p["estado"] != "ok":
            continue
        ops.append({
            "arn": p["arn"],
            "region": p["region"],
            "poner": {**p["crear"], **{k: v[1] for k, v in p["cambiar"].items()}},
            "quitar": sorted(p["borrar"]),
            "antes": p["antes"],
        })
    return ops


def resumen(plan):
    return {
        "recursos": sum(1 for p in plan if p["estado"] == "ok"),
        "crear": sum(len(p["crear"]) for p in plan if p["estado"] == "ok"),
        "cambiar": sum(len(p["cambiar"]) for p in plan if p["estado"] == "ok"),
        "borrar": sum(len(p["borrar"]) for p in plan if p["estado"] == "ok"),
        "conflictos": sum(len(p["conflictos"]) for p in plan),
        "errores": sum(1 for p in plan if p["estado"] == "error"),
        "avisos": sum(len(p["avisos"]) for p in plan),
    }
