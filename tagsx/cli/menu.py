"""El menú de terminal: inventario → CSV/XLSX → editar en Excel → plan → APLICAR.

Formato de columnas del fichero de la opción 2:
  - nombre, id, servicio, region, arn, url: informativas, nunca se tocan.
  - Las del esquema (config 'esquema'): celda vacía = no se toca esa tag (no crea, no
    borra). Celda con valor (incluido "none" literal) = crea o actualiza.
  - Cualquier otra columna (tags ajenas al esquema, descubiertas en el inventario o
    añadidas a mano): celda con valor = crea o actualiza tal cual. Celda vacía = borra
    esa tag si existe en AWS (se entiende que ya no se necesita).
"""
import csv
import glob
import os
from datetime import datetime

from ..core import almacen, aws, config as core_config, existencia
from ..core.aplicar import aplicar
from ..core.arn import normalizar_arn
from ..core.ficheros import escribir_csv, escribir_xlsx, read_input_rows
from ..core.inventario import INFO_COLUMNS, escanear, filas_inventario
from ..core.plan import build_row_plan, columnas_dinamicas
from ..core.scanners import SERVICIOS_DETECTABLES, SERVICIOS_NO_DETECTABLES
from . import pantalla
from .pantalla import color

OUT_DIR = os.getenv("OUT_DIR", "exports")

# Nombre base del fichero a cargar en la opción 2, relativo al directorio desde donde se
# lanza. Se acepta .xlsx (para editar cómodamente en Excel sin pasar por CSV) o .csv; si
# existen los dos, gana el .xlsx.
INPUT_BASENAME = "aws_inventory"


def find_input_file():
    for ext in (".xlsx", ".csv"):
        path = INPUT_BASENAME + ext
        if os.path.exists(path):
            return path
    return INPUT_BASENAME + ".csv"


# ---------------------------------------------------------------------------
# Opción 1: inventario
# ---------------------------------------------------------------------------

def choose_scan_services(config, contexto=""):
    """Los servicios a recorrer con su escáner, o None si se vuelve atrás con Esc."""
    predeterminados = [s for s in config["servicios"] if s in SERVICIOS_DETECTABLES]
    eleccion = pantalla.elegir("Inventario: ¿qué servicios recorrer con su escáner?", [
        ("Predeterminados", f"{len(predeterminados)} de tu configuración"),
        ("Todos", f"los {len(SERVICIOS_DETECTABLES)} con escáner (más lento)"),
    ], contexto)
    if eleccion is None:
        return None
    return SERVICIOS_DETECTABLES if eleccion == 1 else predeterminados


def run_inventory(config, contexto=""):
    servicios = choose_scan_services(config, contexto)
    if servicios is None:
        return False
    titulo(contexto, "Inventario", f"{len(servicios)} servicios con escáner · solo lectura")
    print(color(f"Sin escáner (solo se ven si ya tienen alguna etiqueta): {', '.join(SERVICIOS_NO_DETECTABLES)}", "tenue"))
    print()
    regiones = core_config.regiones_efectivas(config)
    ses = aws.sesion(config["perfil_aws"])
    datos = escanear(ses, regiones, servicios, aviso=print)
    datos["perfil"] = config["perfil_aws"]
    almacen.guardar_snapshot(datos)

    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fieldnames, filas = filas_inventario(datos, config["esquema"])
    csv_path = os.path.join(OUT_DIR, f"aws_inventory_{timestamp}.csv")
    xlsx_path = os.path.join(OUT_DIR, f"aws_inventory_{timestamp}.xlsx")
    escribir_csv(csv_path, fieldnames, filas)
    escribir_xlsx(xlsx_path, fieldnames, filas, INFO_COLUMNS)

    ajenas = [c for c in datos["claves"] if c not in config["esquema"]]
    print()
    print(color(f"Total recursos: {len(filas)}", "acento"))
    print(f"Tags ajenas encontradas ({len(ajenas)}): {', '.join(ajenas) if ajenas else '(ninguna)'}")
    print(f"Inventario generado: {color(xlsx_path, 'negrita')}")
    print(f"                     {csv_path}")
    print(f"Para cargarlo con la opción 2, cópialo como {INPUT_BASENAME}.xlsx en este directorio.")
    return True


# ---------------------------------------------------------------------------
# Opción 2: cargar CSV/XLSX y aplicar
# ---------------------------------------------------------------------------

def write_report(rows, apply_changes):
    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "applied" if apply_changes else "plan"
    path = os.path.join(OUT_DIR, f"tagsx_{suffix}_{timestamp}.csv")

    fieldnames = ["arn", "status", "apply_tags", "remove_keys", "notes", "applied"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "arn": row["arn"],
                "status": row["status"],
                "apply_tags": str(row["apply_tags"]),
                "remove_keys": ",".join(row["remove_keys"]),
                "notes": row["notes"],
                "applied": row["applied"],
            })
    return path


PLAN_SECTIONS = [
    ("ERROR", "ERRORES (no se aplican)"),
    ("AVISO", "AVISOS"),
    ("crear ", "CREAR"),
    ("actualizar ", "ACTUALIZAR"),
    ("borrar ", "BORRAR"),
]
COLOR_SECCION = {"ERRORES (no se aplican)": "rojo", "AVISOS": "ambar", "CREAR": "acento",
                 "ACTUALIZAR": "azul", "BORRAR": "rojo", "OTROS": "tenue"}


def print_grouped_plan(plans):
    """Agrupa las notas de todos los planes por tipo de acción (errores, avisos, crear,
    actualizar, borrar) en vez de imprimirlas recurso a recurso, para que de un vistazo
    se vea cuánto hay de cada tipo."""
    grouped = {title: [] for _, title in PLAN_SECTIONS}
    otros = []

    for p in plans:
        for note in p["notes_list"]:
            for prefix, title in PLAN_SECTIONS:
                if note.startswith(prefix):
                    grouped[title].append((p["arn"], note))
                    break
            else:
                otros.append((p["arn"], note))

    for title, items in list(grouped.items()) + [("OTROS", otros)]:
        if not items:
            continue
        print(color(f"--- {title} ({len(items)}) " + "-" * max(0, 50 - len(title)), COLOR_SECCION[title]))
        last_arn = None
        for arn, note in items:
            if arn != last_arn:
                print(color(arn, "tenue"))
                last_arn = arn
            print(f"  {note}")
        print()


def run_apply_csv(config, contexto=""):
    titulo(contexto, f"Cargar {INPUT_BASENAME}.xlsx/.csv y aplicar", "nada se aplica sin escribir APLICAR")
    input_path = find_input_file()
    if not os.path.exists(input_path):
        print(f"No se encuentra el fichero de entrada: {input_path} (ni .csv ni .xlsx)")
        return

    print(f"Cargando: {input_path}")
    fieldnames, csv_rows = read_input_rows(input_path)
    dynamic_columns, avisos = columnas_dinamicas(fieldnames, config["esquema"])
    for aviso in avisos:
        print(f"AVISO: {aviso}")

    row_by_arn = {}
    region_conocida = {}
    for csv_row in csv_rows:
        arn = normalizar_arn(csv_row.get("arn") or "")
        if not arn:
            print("Fila sin arn, se salta.")
            continue
        row_by_arn[arn] = csv_row
        if (csv_row.get("region") or "").strip():
            region_conocida[arn] = csv_row["region"].strip()

    ses = aws.sesion(config["perfil_aws"])
    regiones = aws.resolver_regiones(ses, list(row_by_arn), region_conocida)
    arns_por_region = {}
    for arn, region in regiones.items():
        if region:
            arns_por_region.setdefault(region, []).append(arn)
    current_tags_by_arn = aws.etiquetas_actuales(ses, arns_por_region)

    skip_reasons = existencia.omitidos(ses, list(row_by_arn), current_tags_by_arn, regiones)
    for arn, region in regiones.items():
        if not region:
            skip_reasons[arn] = "no se sabe en qué región está (bucket de S3 sin permiso para preguntarlo)."

    plans = []
    skipped = []
    for arn, csv_row in row_by_arn.items():
        if arn in skip_reasons:
            skipped.append((arn, skip_reasons[arn]))
            continue
        plan = build_row_plan(arn, csv_row, current_tags_by_arn.get(arn, {}), dynamic_columns, config)
        if plan:
            plan["region"] = regiones[arn]
            plans.append(plan)

    if skipped:
        print()
        title = "AVISOS: recursos omitidos, no se les aplicará ninguna tag"
        print(color(f"--- {title} ({len(skipped)}) " + "-" * 20, "ambar"))
        for arn, reason in skipped:
            print(arn)
            print(f"  AVISO: {reason}")
        print()
        print("Si de verdad ya no existen (no son fantasmas de RDS), quítalos del fichero")
        print("de entrada la próxima vez que lo edites (o vuelve a lanzar la opción 1).")

    if not plans:
        print("No hay cambios que aplicar: el fichero ya coincide con AWS.")
        return

    validos = [p for p in plans if p["status"] != "error"]
    tags_creadas = tags_actualizadas = tags_borradas = 0
    for p in validos:
        for key in p["apply_tags"]:
            if key in current_tags_by_arn.get(p["arn"], {}):
                tags_actualizadas += 1
            else:
                tags_creadas += 1
        tags_borradas += len(p["remove_keys"])

    print()
    print(color(f"Recursos con cambios: {len(validos)}", "negrita"))
    if len(validos) != len(plans):
        print(color(f"Recursos con errores (no se aplican): {len(plans) - len(validos)}", "rojo"))
    print(color(f"Tags a crear: {tags_creadas}", "acento"))
    print(color(f"Tags a actualizar: {tags_actualizadas}", "azul"))
    print(color(f"Tags a borrar: {tags_borradas}", "rojo"))
    print()
    print_grouped_plan(plans)

    plan_path = write_report(plans, apply_changes=False)
    print()
    print(f"Plan generado: {plan_path}")
    if not validos:
        print("Todos los cambios tienen errores: corrige el fichero y vuelve a cargarlo.")
        return

    confirm = input("\n" + color("Escribe APLICAR para aplicar estos cambios en AWS", "ambar")
                    + " (cualquier otra cosa cancela): ").strip()
    if confirm != "APLICAR":
        print("Cancelado, no se ha aplicado nada.")
        return

    ops = [{"arn": p["arn"], "region": p["region"], "poner": p["apply_tags"],
            "quitar": p["remove_keys"], "antes": p["antes"]} for p in validos]
    resultados = {r["arn"]: r for r in aplicar(ses, ops)}

    applied = errors = 0
    for p in validos:
        r = resultados[p["arn"]]
        if r["estado"] == "aplicado":
            p["status"], p["applied"] = "applied", True
            applied += 1
        else:
            p["status"], p["applied"] = ("partial" if r["estado"] == "parcial" else "error"), False
            p["notes"] = f"{p['notes']}; ERROR: {'; '.join(r['errores'])}"
            errors += 1

    lote = almacen.registrar_lote(list(resultados.values()), cuenta=_cuenta(ses),
                                  perfil=config["perfil_aws"], origen="terminal")
    almacen.actualizar_snapshot(list(resultados.values()))
    applied_path = write_report(plans, apply_changes=True)
    print()
    print(color("Finalizado.", "negrita"))
    print(color(f"Aplicados: {applied}", "acento"))
    print(color(f"Errores: {errors}", "rojo" if errors else "tenue"))
    print(f"Informe: {applied_path}")
    if lote:
        print(f"Historial: lote {lote['id']} (se puede deshacer desde la web)")
    if errors:
        print()
        print("Hay errores: revisa el informe, puede ser un recurso ya borrado en AWS")
        print("(o sin permisos). Vuelve a lanzar la opción 1 para refrescar el inventario")
        print(f"y quitar del {INPUT_BASENAME}.xlsx/.csv las filas de recursos que ya no existan.")


def _cuenta(ses):
    try:
        return aws.cuenta(ses)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Opción 3: sugerir los servicios predeterminados a partir del último inventario
# ---------------------------------------------------------------------------

def detectar_servicios_activos(config, contexto=""):
    titulo(contexto, "Detectar servicios activos", "a partir del último inventario")
    datos = almacen.leer_snapshot()
    if not datos:
        files = sorted(glob.glob(os.path.join(OUT_DIR, "aws_inventory_*.csv")))
        if not files:
            print("No hay ningún inventario. Ejecuta primero la opción 1 (con 'todos').")
            return
        with open(files[-1], newline="", encoding="utf-8") as f:
            servicios_vistos = {(row.get("servicio") or "").strip() for row in csv.DictReader(f)}
        print(f"Usando el último inventario: {files[-1]}")
    else:
        servicios_vistos = {r["servicio"] for r in datos["recursos"]}
        print(f"Usando el último inventario ({datos['fecha']}, {len(datos['recursos'])} recursos).")

    # vpc es una reclasificación de ec2 y apigatewayv2 la de las APIs HTTP/WebSocket
    if "vpc" in servicios_vistos:
        servicios_vistos.add("ec2")
    encontrados = [s for s in SERVICIOS_DETECTABLES if s in servicios_vistos]
    vacios = [s for s in SERVICIOS_DETECTABLES if s not in servicios_vistos]

    print()
    print(f"Servicios detectables CON recursos ({len(encontrados)}): {', '.join(encontrados) if encontrados else '(ninguno)'}")
    print(f"Servicios detectables SIN ningún recurso ({len(vacios)}): {', '.join(vacios) if vacios else '(ninguno)'}")
    if not encontrados or encontrados == config["servicios"]:
        return
    print()
    print("Sugerencia para 'servicios' (los predeterminados):")
    print("servicios = [" + ", ".join(f'"{s}"' for s in encontrados) + "]")
    print()
    if pantalla.si_o_no(f"¿Guardarla en {core_config.CONFIG_PATH}?"):
        core_config.guardar({**config, "servicios": encontrados})
        print("Guardado (el fichero anterior queda como .bak).")


# ---------------------------------------------------------------------------

def titulo(contexto, nombre, detalle=""):
    """Al entrar en una opción: la cabecera y qué se está haciendo. Lo que se imprima
    después hace scroll normal y queda en el historial de la terminal."""
    pantalla.limpiar()
    pantalla.cabecera(contexto)
    print()
    print(color(nombre, "negrita") + (color(f" · {detalle}", "tenue") if detalle else ""))
    print()


OPCIONES = [
    ("Inventario", "genera el .xlsx y el .csv para editar en Excel"),
    (f"Cargar {INPUT_BASENAME}.xlsx/.csv y aplicar", "plan, confirmación y aplicar"),
    ("Detectar servicios activos", "sugiere los predeterminados"),
]


def main(config):
    perfil = config["perfil_aws"] or os.environ.get("AWS_PROFILE") or "por defecto"
    contexto = f"perfil {perfil} · {', '.join(core_config.regiones_efectivas(config))} + global"
    acciones = [run_inventory, run_apply_csv, detectar_servicios_activos]
    elegida = 0
    while True:
        opcion = pantalla.elegir("¿Qué quieres hacer?", OPCIONES, contexto, elegida,
                                 ayuda="↑/↓ para moverte · Intro o número para elegir · Esc para salir")
        if opcion is None:
            print("Hasta luego.")
            return
        elegida = opcion
        try:
            if acciones[opcion](config, contexto) is False:
                continue        # Esc en un paso intermedio: vuelve al menú sin pausa
        except (KeyboardInterrupt, EOFError):
            print("\n" + color("Cancelado.", "ambar"))
        except Exception as exc:
            print("\n" + color(f"Error: {exc}", "rojo"))
        if not pantalla.pausa():
            return
