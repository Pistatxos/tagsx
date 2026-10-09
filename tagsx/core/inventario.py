"""El inventario: Tagging API + escáneres propios, por región y lo global en us-east-1."""
from datetime import datetime

from .arn import (
    REGION_GLOBAL, SERVICIOS_ARN_GLOBALES, build_url, classify_service, friendly_name,
    normalizar_arn, parse_arn, region_de,
)
from .aws import cliente_tagging, cuenta, get_all_resources
from .reglas import etiquetas_visibles
from .scanners import SCANNERS, SCANNERS_GLOBALES_EXTRA, SERVICIOS_GLOBALES

# Columnas informativas del CSV/XLSX: nunca se tocan al aplicar
INFO_COLUMNS = ["nombre", "id", "servicio", "region", "arn", "url"]


def _sin_aviso(_mensaje):
    pass


def escanear(ses, regiones, servicios, aviso=None):
    """Devuelve {"fecha", "cuenta", "regiones", "servicios", "recursos", "claves"}.

    Cada recurso: {arn, region, nombre, id, servicio, tipo, url, tags}. `region` es donde
    se lee y se etiqueta (us-east-1 para lo global, la del bucket para S3). `claves` son
    todas las etiquetas encontradas, en orden de aparición.
    """
    aviso = aviso or _sin_aviso
    account = cuenta(ses)
    items = {}  # arn -> (item de AWS, región donde se encontró)
    seen_arns = set()

    def anadir(item, region_encontrada):
        arn = normalizar_arn(item["ResourceARN"])
        if arn in items:
            return
        seen_arns.add(arn)
        seen_arns.add(item["ResourceARN"])
        items[arn] = (item, item.get("Region") or region_encontrada)

    def pasar_escaner(nombre, escaner, region):
        try:
            for item in escaner(ses, region, account, seen_arns):
                anadir(item, region)
        except Exception as exc:
            aviso(f"  Aviso: no se pudo completar el escaneo de '{nombre}' en {region}: {exc}")

    for region in regiones:
        aviso(f"Escaneando región: {region}")
        try:
            for item in get_all_resources(cliente_tagging(ses, region)):
                anadir(item, region)
        except Exception as exc:
            aviso(f"  Aviso: no se pudo leer la Tagging API en {region}: {exc}")
            continue
        for servicio in servicios:
            if servicio in SERVICIOS_GLOBALES or servicio not in SCANNERS:
                continue
            pasar_escaner(servicio, SCANNERS[servicio], region)

    # Lo global, una sola vez y en us-east-1: si se usara otra región, la Tagging API lo
    # devolvía «sin tags». Si us-east-1 ya estaba entre las regiones, ya está leído.
    aviso(f"Escaneando lo global (IAM, CloudFront, Route 53…) en {REGION_GLOBAL}")
    if REGION_GLOBAL not in regiones:
        cliente = cliente_tagging(ses, REGION_GLOBAL)
        # Un filtro por llamada: si uno no lo admite la cuenta, los demás se leen igual
        for filtro in sorted(SERVICIOS_ARN_GLOBALES - {"waf"}) + ["wafv2"]:
            try:
                for item in get_all_resources(cliente, [filtro]):
                    arn = item["ResourceARN"]
                    # De wafv2 en us-east-1 solo interesa lo de CloudFront (…:global/…)
                    if not parse_arn(arn)[3] or ":global/" in arn:
                        anadir(item, REGION_GLOBAL)
            except Exception as exc:
                aviso(f"  Aviso: no se pudo leer '{filtro}' en {REGION_GLOBAL}: {exc}")
    for servicio in servicios:
        if servicio in SERVICIOS_GLOBALES and servicio in SCANNERS:
            pasar_escaner(servicio, SCANNERS[servicio], REGION_GLOBAL)
        if servicio in SCANNERS_GLOBALES_EXTRA:
            pasar_escaner(servicio, SCANNERS_GLOBALES_EXTRA[servicio], REGION_GLOBAL)

    recursos, claves, vistas = [], [], set()
    for arn, (item, region_encontrada) in items.items():
        tags = etiquetas_visibles(item.get("Tags"))
        for clave in tags:
            if clave not in vistas:
                vistas.add(clave)
                claves.append(clave)
        recursos.append(recurso(arn, region_de(arn) or region_encontrada, tags, account))

    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "cuenta": account,
        "regiones": list(regiones),
        "servicios": list(servicios),
        "recursos": recursos,
        "claves": claves,
    }


def recurso(arn, region, tags, account=""):
    service, resource_type, resource_id, _, arn_account = parse_arn(arn)
    return {
        "arn": arn,
        "region": region or "",
        "nombre": tags.get("Name") or friendly_name(resource_id),
        "id": resource_id,
        "servicio": classify_service(service, resource_type),
        "tipo": resource_type,
        "url": build_url(service, resource_type, resource_id, arn, region or REGION_GLOBAL,
                         arn_account or account),
        "tags": tags,
    }


def filas_inventario(datos, esquema):
    """(cabeceras, filas) del CSV/XLSX: informativas + esquema + el resto de etiquetas."""
    ajenas = [c for c in datos["claves"] if c not in esquema]
    fieldnames = INFO_COLUMNS + list(esquema) + ajenas
    filas = []
    for r in datos["recursos"]:
        fila = {c: r.get(c, "") for c in INFO_COLUMNS}
        for clave in list(esquema) + ajenas:
            fila[clave] = r["tags"].get(clave, "")
        filas.append(fila)
    return fieldnames, filas
