#!/usr/bin/env python3
"""
Herramienta individual para revisar y modificar tags de un ARN concreto.

Flujo:
  1. Ver tags actuales de un recurso.
  2. Modificar tags del recurso usando la configuracion de este archivo.

La opcion de modificar siempre muestra un plan y exige escribir APLICAR.
"""
import os

import boto3


REGION = os.getenv("AWS_REGION", "eu-south-2")

# Si se rellena, el script usara este ARN directamente.
# Si esta vacio, preguntara el ARN por terminal.
RESOURCE_ARN = ""

# Tags nuevas que se quieren crear en el recurso.
# Si la tag ya existe, se conserva el valor actual y no se sobrescribe.
NEWS_TAG = {
    "Application": "CORE",
    "Environment": "PROD",
}

# Tags antiguas que se quieren cambiar por una nueva key.
# Formato simple: "BBDD": "Service" mantiene el value original.
# Formato con value fijo: "BBDD": {"new_key": "Service", "new_value": "ssm"}
RENAMES_TAG = {
    # "owner": "Owner",
    # "tagOwner": "Owner",
    "BBDD": {"new_key": "Service", "new_value": "ssm"},
    # "Recurso": "Resource",
}

# Tags que se quieren borrar directamente tras confirmacion.
DELETE_TAGS = [
    # "DATA",
]


def get_client():
    return boto3.client("resourcegroupstaggingapi", region_name=REGION)


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


def print_tags(arn, tags):
    service, resource_type = parse_arn(arn)

    print()
    print(f"ARN: {arn}")
    print(f"Region: {REGION}")
    print(f"Service: {service}")
    print(f"Resource type: {resource_type}")
    print()
    print("Tags actuales:")

    if not tags:
        print("  Sin tags")
        return

    for key, value in sorted(tags.items()):
        print(f"  {key}={value}")


def normalize_rename_rule(old_key, old_value):
    rule = RENAMES_TAG[old_key]
    if isinstance(rule, dict):
        return rule["new_key"], rule.get("new_value", old_value)
    return rule, old_value


def build_plan(tags):
    tags_to_apply = {}
    keys_to_remove = []
    notes = []

    for key, value in NEWS_TAG.items():
        if key in tags:
            notes.append(f"{key} ya existe con value '{tags[key]}'. Se conserva.")
            continue

        tags_to_apply[key] = value
        notes.append(f"crear {key}={value}")

    for old_key in sorted(RENAMES_TAG):
        if old_key not in tags:
            notes.append(f"{old_key} no existe. No se renombra.")
            continue

        old_value = tags[old_key]
        new_key, new_value = normalize_rename_rule(old_key, old_value)

        if new_key in tags:
            notes.append(
                f"{new_key} ya existe con value '{tags[new_key]}'. "
                f"Se conserva y se borrara {old_key}."
            )
        elif new_key in tags_to_apply:
            notes.append(
                f"{new_key} ya esta planificada con value "
                f"'{tags_to_apply[new_key]}'. Se conserva ese plan."
            )
        else:
            tags_to_apply[new_key] = new_value
            notes.append(f"crear {new_key}={new_value} desde {old_key}={old_value}")

        keys_to_remove.append(old_key)

    for key in DELETE_TAGS:
        if key in tags and key not in keys_to_remove:
            keys_to_remove.append(key)
            notes.append(f"borrar {key}")
        elif key not in tags:
            notes.append(f"{key} no existe. No se borra.")

    return tags_to_apply, sorted(set(keys_to_remove)), notes


def print_plan(tags_to_apply, keys_to_remove, notes):
    print()
    print("Plan:")

    print("  Tags a crear/actualizar:")
    if tags_to_apply:
        for key, value in sorted(tags_to_apply.items()):
            print(f"    {key}={value}")
    else:
        print("    Ninguna")

    print("  Tags a borrar:")
    if keys_to_remove:
        for key in keys_to_remove:
            print(f"    {key}")
    else:
        print("    Ninguna")

    print("  Notas:")
    if notes:
        for note in notes:
            print(f"    {note}")
    else:
        print("    Sin notas")


def apply_plan(client, arn, tags_to_apply, keys_to_remove):
    if tags_to_apply:
        client.tag_resources(ResourceARNList=[arn], Tags=tags_to_apply)

    if keys_to_remove:
        client.untag_resources(ResourceARNList=[arn], TagKeys=keys_to_remove)


def ask_arn():
    if RESOURCE_ARN.strip():
        arn = RESOURCE_ARN.strip()
        print(f"Usando RESOURCE_ARN configurado: {arn}")
        return arn

    return input("ARN: ").strip()


def confirm_apply():
    confirm = input("Escribe APLICAR para confirmar cambios en AWS: ").strip()
    if confirm != "APLICAR":
        print("Confirmacion incorrecta. No se ha aplicado ningun cambio en AWS.")
        return False
    return True


def view_tags(client):
    arn = ask_arn()
    tags = get_resource_tags(client, arn)
    if tags is None:
        print("No se ha encontrado el recurso o no es visible para Resource Groups Tagging API.")
        return

    print_tags(arn, tags)


def modify_tags(client):
    arn = ask_arn()
    tags = get_resource_tags(client, arn)
    if tags is None:
        print("No se ha encontrado el recurso o no es visible para Resource Groups Tagging API.")
        return

    print_tags(arn, tags)
    tags_to_apply, keys_to_remove, notes = build_plan(tags)
    print_plan(tags_to_apply, keys_to_remove, notes)

    if not tags_to_apply and not keys_to_remove:
        print("No hay cambios que aplicar.")
        return

    if not confirm_apply():
        return

    apply_plan(client, arn, tags_to_apply, keys_to_remove)
    print("Cambios aplicados en AWS.")


def main():
    client = get_client()

    while True:
        print()
        print("Que quieres hacer?")
        print("1. Ver tags de un recurso")
        print("2. Modificar tags de un recurso")
        print("3. Salir")

        choice = input("Opcion [1-3]: ").strip()

        if choice == "1":
            view_tags(client)
        elif choice == "2":
            modify_tags(client)
        elif choice == "3":
            print("Salida sin cambios.")
            return
        else:
            print("Opcion no valida.")


if __name__ == "__main__":
    main()
