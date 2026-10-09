#!/usr/bin/env python3
"""
Herramienta para borrar tags AWS de forma controlada.

Modos:
  1. Ver tags de un ARN concreto.
  2. Borrar tags de un ARN concreto.
  3. Borrar tags por key en todos los recursos visibles.

Siempre muestra un plan y exige escribir BORRAR antes de aplicar cambios.
"""
import os

import boto3


REGIONS = os.getenv("AWS_REGIONS", os.getenv("AWS_REGION", "eu-south-2")).split(",")

# Si se rellena, el script usara este ARN directamente.
# Si esta vacio, preguntara el ARN por terminal en los modos individuales.
RESOURCE_ARN = ""

# Lista de ARNs para trabajar en lote sin escanear todos los servicios.
# Tiene prioridad sobre RESOURCE_ARN.
RESOURCE_ARNS = [
    # "arn:aws:ssm:eu-south-2:123456789012:parameter/mi-app/dev/host",
]

# Tags concretas que se quieren borrar.
# Ejemplo: ["DATA", "BBDD"]
DELETE_TAGS = [
    # "Temporal",
    # "owner",
]

# Borrar todas las tags del recurso en modo individual.
# Por seguridad, viene desactivado.
DELETE_ALL_TAGS = False

SKIP_KEY_PREFIXES = (
    "aws:",
    "kubernetes.io/",
)


def get_client(region):
    return boto3.client("resourcegroupstaggingapi", region_name=region)


def get_all_resources(client):
    paginator = client.get_paginator("get_resources")
    for page in paginator.paginate(ResourcesPerPage=100):
        for item in page.get("ResourceTagMappingList", []):
            yield item


def get_resource_tags(client, arn):
    response = client.get_resources(ResourceARNList=[arn])
    mappings = response.get("ResourceTagMappingList", [])
    if not mappings:
        return None

    return {tag["Key"]: tag["Value"] for tag in mappings[0].get("Tags", [])}


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


def should_skip_key(key):
    return key.startswith(SKIP_KEY_PREFIXES)


def ask_arn():
    if RESOURCE_ARN.strip():
        arn = RESOURCE_ARN.strip()
        print(f"Usando RESOURCE_ARN configurado: {arn}")
        return arn

    return input("ARN: ").strip()


def get_configured_arns():
    return [arn.strip() for arn in RESOURCE_ARNS if arn.strip()]


def ask_region_for_arn():
    region = os.getenv("AWS_REGION", "eu-south-2")
    if len([item for item in REGIONS if item.strip()]) == 1:
        region = [item.strip() for item in REGIONS if item.strip()][0]

    selected = input(f"Region [{region}]: ").strip()
    return selected or region


def confirm_delete():
    confirm = input("Escribe BORRAR para confirmar cambios en AWS: ").strip()
    if confirm != "BORRAR":
        print("Confirmacion incorrecta. No se ha borrado ninguna tag en AWS.")
        return False
    return True


def print_tags(region, arn, tags):
    service, resource_type = parse_arn(arn)

    print()
    print(f"ARN: {arn}")
    print(f"Region: {region}")
    print(f"Service: {service}")
    print(f"Resource type: {resource_type}")
    print()
    print("Tags actuales:")

    if not tags:
        print("  Sin tags")
        return

    for key, value in sorted(tags.items()):
        print(f"  {key}={value}")


def build_delete_keys(tags):
    if DELETE_ALL_TAGS:
        return sorted(key for key in tags if not should_skip_key(key))

    return sorted(key for key in DELETE_TAGS if key in tags and not should_skip_key(key))


def print_delete_plan(arn, keys_to_delete):
    print()
    print(f"Plan para: {arn}")
    print("  Tags a borrar:")
    if keys_to_delete:
        for key in keys_to_delete:
            print(f"    {key}")
    else:
        print("    Ninguna")


def view_resource_tags():
    arns = get_configured_arns()
    if not arns:
        region = ask_region_for_arn()
        arns = [ask_arn()]
    else:
        region = os.getenv("AWS_REGION", "eu-south-2")
        print(f"Usando RESOURCE_ARNS configurados: {len(arns)}")

    clients = {}
    for arn in arns:
        arn_region = parse_arn_region(arn, region)
        if arn_region not in clients:
            clients[arn_region] = get_client(arn_region)

        tags = get_resource_tags(clients[arn_region], arn)
        if tags is None:
            print(f"No se ha encontrado el recurso o no es visible: {arn}")
            continue

        print_tags(arn_region, arn, tags)


def delete_resource_tags():
    arns = get_configured_arns()
    if not arns:
        region = ask_region_for_arn()
        arns = [ask_arn()]
    else:
        region = os.getenv("AWS_REGION", "eu-south-2")
        print(f"Usando RESOURCE_ARNS configurados: {len(arns)}")

    clients = {}
    rows = []

    for arn in arns:
        arn_region = parse_arn_region(arn, region)
        if arn_region not in clients:
            clients[arn_region] = get_client(arn_region)

        tags = get_resource_tags(clients[arn_region], arn)
        if tags is None:
            print(f"No se ha encontrado el recurso o no es visible: {arn}")
            continue

        print_tags(arn_region, arn, tags)
        keys_to_delete = build_delete_keys(tags)
        print_delete_plan(arn, keys_to_delete)

        if keys_to_delete:
            rows.append({
                "region": arn_region,
                "arn": arn,
                "keys_to_delete": keys_to_delete,
            })

    if not rows:
        print("No hay tags que borrar.")
        return

    if DELETE_ALL_TAGS:
        print("AVISO: DELETE_ALL_TAGS=True borrara todas las tags no protegidas de los ARNs planificados.")

    if not confirm_delete():
        return

    errors = 0
    applied = 0
    for row in rows:
        try:
            clients[row["region"]].untag_resources(
                ResourceARNList=[row["arn"]],
                TagKeys=row["keys_to_delete"],
            )
            applied += 1
        except Exception as exc:
            errors += 1
            print(f"ERROR {row['arn']}: {exc}")

    print()
    print(f"Recursos modificados: {applied}")
    print(f"Errores: {errors}")


def delete_tags_globally():
    if DELETE_ALL_TAGS:
        print("DELETE_ALL_TAGS=True solo esta permitido en modo ARN individual.")
        return

    keys_to_match = [key for key in DELETE_TAGS if key]
    if not keys_to_match:
        print("DELETE_TAGS esta vacio. No hay nada que borrar.")
        return

    rows = []

    for region in REGIONS:
        region = region.strip()
        if not region:
            continue

        print(f"Revisando region: {region}")
        client = get_client(region)

        for resource in get_all_resources(client):
            arn = resource["ResourceARN"]
            tags = {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}
            keys_to_delete = sorted(key for key in keys_to_match if key in tags and not should_skip_key(key))

            if keys_to_delete:
                rows.append({
                    "region": region,
                    "arn": arn,
                    "keys_to_delete": keys_to_delete,
                })

    print()
    print(f"Recursos con tags a borrar: {len(rows)}")
    for row in rows:
        print(f"{row['region']} {row['arn']}")
        print(f"  borrar: {', '.join(row['keys_to_delete'])}")

    if not rows:
        print("No hay tags que borrar.")
        return

    if not confirm_delete():
        return

    clients = {}
    errors = 0
    applied = 0
    for row in rows:
        region = row["region"]
        if region not in clients:
            clients[region] = get_client(region)

        try:
            clients[region].untag_resources(
                ResourceARNList=[row["arn"]],
                TagKeys=row["keys_to_delete"],
            )
            applied += 1
        except Exception as exc:
            errors += 1
            print(f"ERROR {row['arn']}: {exc}")

    print()
    print(f"Recursos modificados: {applied}")
    print(f"Errores: {errors}")


def main():
    while True:
        print()
        print("Que quieres hacer?")
        print("1. Ver tags de un ARN")
        print("2. Borrar tags de un ARN")
        print("3. Borrar DELETE_TAGS en todos los recursos")
        print("4. Salir")

        choice = input("Opcion [1-4]: ").strip()

        if choice == "1":
            view_resource_tags()
        elif choice == "2":
            delete_resource_tags()
        elif choice == "3":
            delete_tags_globally()
        elif choice == "4":
            print("Salida sin cambios.")
            return
        else:
            print("Opcion no valida.")


if __name__ == "__main__":
    main()
