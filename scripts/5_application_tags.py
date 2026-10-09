#!/usr/bin/env python3
"""
Normalizacion especifica de la tag Application.

Convierte values antiguos de Application en las tags finales Application,
Project y Service. Siempre genera plan y exige confirmar con APLICAR.
"""
import csv
import os
from datetime import datetime

import boto3


REGIONS = os.getenv("AWS_REGIONS", os.getenv("AWS_REGION", "eu-south-2")).split(",")
OUT_DIR = os.getenv("OUT_DIR", "exports")
SERVICE_FROM_ARN = "__service_from_arn__"

# Si se rellena, trabaja solo sobre estos ARNs. Si esta vacio, escanea todo.
RESOURCE_ARNS = [
    # "arn:aws:ec2:eu-south-2:123456789012:instance/i-...",
]

# None significa eliminar Application.
APPLICATION_MAP = {
    "WEB": {"Application": "web", "Project": "portal", "Service": SERVICE_FROM_ARN},
    "CORE": {"Application": "core"},
    "DATA": {"Application": "data"},
    "ETL": {"Application": "data", "Project": "etl", "Service": "lambda"},
    "AI": {"Application": "ai"},
    "TODOS": None,
}

LOWERCASE_TARGET_KEYS = {
    "Application",
    "Project",
    "Service",
}


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


def build_plan(region, resource):
    arn = resource["ResourceARN"]
    service, resource_type = parse_arn(arn)
    tags = {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}
    current_value = tags.get("Application")

    found_mapping, mapping = get_application_mapping(current_value)
    if current_value is None or not found_mapping:
        return None

    tags_to_apply = {}
    keys_to_remove = []
    notes = []
    status = "planned"

    if mapping is None:
        keys_to_remove.append("Application")
        notes.append("Application marcado para eliminar")
    else:
        for key, new_value in resolve_mapping(mapping, service).items():
            new_value = normalize_target_value(key, new_value)
            existing_value = tags.get(key)

            if key == "Application":
                if existing_value != new_value:
                    tags_to_apply[key] = new_value
                    notes.append(f"actualizar Application: {existing_value} -> {new_value}")
                continue

            if existing_value is None:
                tags_to_apply[key] = new_value
                notes.append(f"crear {key}={new_value}")
            elif existing_value == new_value:
                notes.append(f"{key} ya existe con el value correcto")
            elif is_same_value_different_case(key, existing_value, new_value):
                tags_to_apply[key] = new_value
                notes.append(f"normalizar {key}: {existing_value} -> {new_value}")
            elif should_lowercase_existing_value(key, existing_value):
                tags_to_apply[key] = existing_value.lower()
                notes.append(
                    f"{key} ya existe con value '{existing_value}'. "
                    f"Se conserva como '{existing_value.lower()}'"
                )
            else:
                notes.append(f"{key} ya existe con value '{existing_value}'. Se conserva")

    if not tags_to_apply and not keys_to_remove:
        return None

    return {
        "region": region,
        "service": service,
        "resource_type": resource_type,
        "arn": arn,
        "status": status,
        "old_application": current_value,
        "apply_tags": str(tags_to_apply),
        "remove_keys": ",".join(keys_to_remove),
        "notes": "; ".join(notes),
        "applied": False,
        "_tags_to_apply": tags_to_apply,
        "_keys_to_remove": keys_to_remove,
    }


def get_application_mapping(value):
    if value in APPLICATION_MAP:
        return True, APPLICATION_MAP[value]

    if value is None:
        return False, None

    for old_value, mapping in APPLICATION_MAP.items():
        if old_value.lower() == value.lower():
            return True, mapping

    return False, None


def resolve_mapping(mapping, arn_service):
    if mapping is None:
        return None

    resolved = {}
    for key, value in mapping.items():
        if value == SERVICE_FROM_ARN:
            resolved[key] = arn_service
        else:
            resolved[key] = value
    return resolved


def normalize_target_value(key, value):
    if key in LOWERCASE_TARGET_KEYS:
        return value.lower()
    return value


def is_same_value_different_case(key, existing_value, new_value):
    return (
        key in LOWERCASE_TARGET_KEYS
        and existing_value.lower() == new_value.lower()
        and existing_value != new_value
    )


def should_lowercase_existing_value(key, existing_value):
    return key in LOWERCASE_TARGET_KEYS and existing_value != existing_value.lower()


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
    path = os.path.join(OUT_DIR, f"aws_application_tags_{suffix}_{timestamp}.csv")

    fieldnames = [
        "region",
        "service",
        "resource_type",
        "arn",
        "status",
        "old_application",
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
            print(f"  Application={row['old_application']}")
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
