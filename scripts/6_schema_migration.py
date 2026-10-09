#!/usr/bin/env python3
"""
Migracion al esquema completo de tags (Application, Project, Product,
Component, Owner, Service).

Aplica el catalogo acordado: para cada recurso, resuelve Application/Project
segun tenga hoy (APPLICATION_OVERRIDE tiene prioridad sobre el catalogo de
Project), fija Owner segun el alias de correo corporativo, migra Resource a
Component, y fuerza Service al valor derivado del propio ARN del recurso.

No toca Name, Environment ni ManagedBy: quedan pendientes de un catalogo
aparte. Siempre genera plan y exige confirmar con APLICAR.
"""
import csv
import os
from datetime import datetime

import boto3


REGIONS = os.getenv("AWS_REGIONS", os.getenv("AWS_REGION", "eu-south-2")).split(",")
OUT_DIR = os.getenv("OUT_DIR", "exports")

# Si se rellena, trabaja solo sobre estos ARNs. Si esta vacio, escanea todo.
RESOURCE_ARNS = [
    # "arn:aws:ec2:eu-south-2:123456789012:instance/i-...",
]

# Correccion puntual por ARN: fija el Product real de recursos concretos fuera
# del flujo normal del catalogo (ver PRODUCT_ALREADY_SET_GUARD mas abajo).
PRODUCT_FIX_ARNS = {
    # "arn:aws:ec2:eu-south-2:123456789012:instance/i-0123456789abcdef0": "mi-producto",
}

# Prioridad sobre PROJECT_CATALOG: se mira primero por el value actual de
# Application (case-insensitive). Cubre casos de Application que no
# llevan tag Project.
APPLICATION_OVERRIDE = {
    "portal": {"Application": "web", "Project": "portal", "Product": "portal"},
}

# Catalogo por value actual de Project (case-insensitive). Entradas sin la key
# "Application" dejan Application tal cual esta hoy: son placeholders
# pendientes de revisar mas adelante con el ARN/servicio real.
PROJECT_CATALOG = {
    "portal": {"Application": "web", "Project": "portal", "Product": "portal"},
    "facturacion": {"Application": "core", "Project": "facturacion", "Product": "none"},
    "etl": {"Application": "data", "Project": "etl", "Product": "none"},
    "visor": {"Application": "data", "Project": "etl", "Product": "visor", "Component": "frontend"},

    # Placeholders: Application no se toca, Project se deja en minuscula tal
    # cual, Product=none. Pendiente de revisar caso a caso con el ARN.
    "core": {"Project": "core", "Product": "none"},
    "data": {"Project": "data", "Product": "none"},
}

# Alias de correo corporativo (sin dominio) para Owner. Los que ya estan bien no
# necesitan entrada.
OWNER_MAP = {
    "Ana": "agarcia",
    "ana": "agarcia",
    "Luis": "lperez",
}

# Normalizacion de nombre de servicio derivado del ARN al value de Service.
SERVICE_NORMALIZE = {
    "apigateway": "api",
}

LOWERCASE_KEYS = {"Application", "Project", "Product", "Component", "Service"}


def get_client(region):
    return boto3.client("resourcegroupstaggingapi", region_name=region)


def get_all_resources(client):
    paginator = client.get_paginator("get_resources")
    for page in paginator.paginate(ResourcesPerPage=100):
        for item in page.get("ResourceTagMappingList", []):
            yield item


def get_resources_by_arn(client, arns):
    for arn in arns:
        response = client.get_resources(ResourceARNList=[arn])
        for item in response.get("ResourceTagMappingList", []):
            yield item


def parse_arn(arn):
    parts = arn.split(":", 5)
    service = parts[2] if len(parts) > 2 else ""
    resource = parts[5] if len(parts) > 5 else ""
    resource = resource.lstrip("/")

    if "/" in resource:
        resource_type = resource.split("/", 1)[0]
    elif ":" in resource:
        resource_type = resource.split(":", 1)[0]
    else:
        resource_type = resource

    return service, resource_type


def parse_arn_region(arn, default_region):
    parts = arn.split(":", 5)
    if len(parts) > 3 and parts[3]:
        return parts[3]
    return default_region


def resolve_catalog_mapping(tags):
    application = tags.get("Application")
    if application:
        for key, mapping in APPLICATION_OVERRIDE.items():
            if key.lower() == application.lower():
                return mapping

    project = tags.get("Project")
    if project:
        for key, mapping in PROJECT_CATALOG.items():
            if key.lower() == project.lower():
                return mapping

    return None


def normalize(key, value):
    if key in LOWERCASE_KEYS and value is not None:
        return value.lower()
    return value


def build_plan(region, resource):
    arn = resource["ResourceARN"]
    service, resource_type = parse_arn(arn)
    tags = {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}

    if not tags:
        # Paso 1: solo normalizar lo que ya tiene alguna tag. Los recursos sin
        # ninguna tag (stacks de CloudFormation, reglas de EventBridge, SSM,
        # etc.) se revisan mas adelante, servicio a servicio.
        return None

    tags_to_apply = {}
    keys_to_remove = []
    notes = []

    if arn in PRODUCT_FIX_ARNS:
        fixed_product = normalize("Product", PRODUCT_FIX_ARNS[arn])
        if tags.get("Product") != fixed_product:
            tags_to_apply["Product"] = fixed_product
            notes.append(f"Product corregido tras regresion: {tags.get('Product')!r} -> {fixed_product!r}")

    # Solo se resuelve el catalogo si el recurso todavia no tiene Product: una
    # vez migrado, Project ya vale el destino final (p.ej. "portal"), que puede
    # coincidir con otra entrada valida del catalogo y pisar Product si se
    # re-resuelve en una segunda ejecucion.
    if "Product" not in tags:
        mapping = resolve_catalog_mapping(tags)
        if mapping:
            for key in ("Application", "Project", "Product", "Component"):
                if key not in mapping:
                    continue
                new_value = normalize(key, mapping[key])
                existing_value = tags.get(key)
                if existing_value != new_value:
                    tags_to_apply[key] = new_value
                    notes.append(f"{key}: {existing_value!r} -> {new_value!r}")

    if "Resource" in tags:
        keys_to_remove.append("Resource")
        if "Component" not in tags_to_apply and "Component" not in tags:
            component_value = normalize("Component", tags["Resource"])
            tags_to_apply["Component"] = component_value
            notes.append(f"Component creado desde Resource: {component_value!r}")
        notes.append("Resource eliminado (sustituida por Component)")

    current_owner = tags.get("Owner")
    if current_owner in OWNER_MAP:
        new_owner = OWNER_MAP[current_owner]
        if current_owner != new_owner:
            tags_to_apply["Owner"] = new_owner
            notes.append(f"Owner: {current_owner!r} -> {new_owner!r}")

    normalized_service = normalize("Service", SERVICE_NORMALIZE.get(service, service))
    current_service = tags.get("Service")

    if current_service == "cloudformation" and normalized_service != "cloudformation" and "ManagedBy" not in tags:
        tags_to_apply["ManagedBy"] = "cloudformation"
        notes.append("ManagedBy creado desde Service incorrecto: 'cloudformation'")

    if current_service != normalized_service:
        tags_to_apply["Service"] = normalized_service
        notes.append(f"Service: {current_service!r} -> {normalized_service!r}")

    if not tags_to_apply and not keys_to_remove:
        return None

    return {
        "region": region,
        "service": service,
        "resource_type": resource_type,
        "arn": arn,
        "status": "planned",
        "old_application": tags.get("Application"),
        "old_project": tags.get("Project"),
        "old_owner": current_owner,
        "apply_tags": str(tags_to_apply),
        "remove_keys": ",".join(keys_to_remove),
        "notes": "; ".join(notes),
        "applied": False,
        "_tags_to_apply": tags_to_apply,
        "_keys_to_remove": keys_to_remove,
    }


def ask_apply():
    print("Que quieres hacer?")
    print("1. Ver cambios sin aplicar")
    print("2. Aplicar cambios en AWS")
    print("3. Salir")

    choice = input("Opcion [1-3]: ").strip()
    if choice == "1":
        return False
    if choice == "2":
        confirm = input("Escribe APLICAR para confirmar cambios en AWS: ").strip()
        if confirm != "APLICAR":
            raise SystemExit("Confirmacion incorrecta. No se ha aplicado ningun cambio en AWS.")
        return True
    raise SystemExit("Salida sin cambios")


def write_report(rows, apply_changes):
    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "applied" if apply_changes else "plan"
    path = os.path.join(OUT_DIR, f"aws_schema_migration_{suffix}_{timestamp}.csv")

    fieldnames = [
        "region",
        "service",
        "resource_type",
        "arn",
        "status",
        "old_application",
        "old_project",
        "old_owner",
        "apply_tags",
        "remove_keys",
        "notes",
        "applied",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    return path


def apply_plan(client, row):
    try:
        if row["_tags_to_apply"]:
            client.tag_resources(ResourceARNList=[row["arn"]], Tags=row["_tags_to_apply"])

        if row["_keys_to_remove"]:
            client.untag_resources(ResourceARNList=[row["arn"]], TagKeys=row["_keys_to_remove"])

        row["status"] = "applied"
        row["applied"] = True
    except Exception as exc:
        row["status"] = "error"
        row["notes"] = f"{row['notes']}; ERROR: {exc}"
        row["applied"] = False

    return row


def get_configured_arns_by_region(default_region):
    arns_by_region = {}
    for arn in [item.strip() for item in RESOURCE_ARNS if item.strip()]:
        region = parse_arn_region(arn, default_region)
        arns_by_region.setdefault(region, []).append(arn)
    return arns_by_region


def main():
    apply_changes = ask_apply()
    rows = []
    arns_by_region = get_configured_arns_by_region(os.getenv("AWS_REGION", "eu-south-2"))

    regions = arns_by_region.keys() if arns_by_region else REGIONS

    for region in regions:
        region = region.strip()
        if not region:
            continue

        print(f"Revisando region: {region}")
        client = get_client(region)

        if arns_by_region:
            resources = get_resources_by_arn(client, arns_by_region[region])
        else:
            resources = get_all_resources(client)

        for resource in resources:
            row = build_plan(region, resource)
            if row is None:
                continue

            if apply_changes:
                row = apply_plan(client, row)

            rows.append(row)
            print(f"{row['status']}: {row['arn']}")
            print(f"  Application={row['old_application']}  Project={row['old_project']}  Owner={row['old_owner']}")
            print(f"  aplicar: {row['apply_tags']}")
            if row["remove_keys"]:
                print(f"  borrar: {row['remove_keys']}")
            if row["notes"]:
                print(f"  notas: {row['notes']}")

    report_path = write_report(rows, apply_changes)

    print()
    print(f"Cambios detectados: {len(rows)}")
    print(f"Aplicados: {sum(1 for row in rows if row['status'] == 'applied')}")
    print(f"Errores: {sum(1 for row in rows if row['status'] == 'error')}")
    print(f"Informe generado: {report_path}")


if __name__ == "__main__":
    main()
