#!/usr/bin/env python3
import csv
import os
from collections import defaultdict
from datetime import datetime

import boto3


REGIONS = os.getenv("AWS_REGIONS", os.getenv("AWS_REGION", "eu-south-2")).split(",")
OUT_DIR = os.getenv("OUT_DIR", "exports")

# Configuracion editable: primero migramos keys antiguas a la key estandar.
KEY_RENAMES = {
    # "owner": "Owner",
    # "tagOwner": "Owner",
    "Purpose": "Service",
    # "Recurso": "Resource",
}

# Configuracion editable: despues normalizamos values de la key estandar.
VALUE_REPLACEMENTS = {
    # "Owner": {
    #     "Ana": "agarcia",
    #     "ANA": "agarcia",
    # },
    # "Service": {
    #     "bbdd": "db",
    # },
}

SKIP_KEY_PREFIXES = (
    "aws:",
    "kubernetes.io/",
)


class AwsTagCleaner:
    def __init__(self, region: str):
        self.region = region
        self.client = boto3.client("resourcegroupstaggingapi", region_name=region)

    def get_all_resources(self):
        paginator = self.client.get_paginator("get_resources")
        for page in paginator.paginate(ResourcesPerPage=100):
            for item in page.get("ResourceTagMappingList", []):
                yield item

    def build_resource_plan(self, resource):
        arn = resource["ResourceARN"]
        service, resource_type = parse_arn(arn)
        tags = {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}

        candidates_by_key = defaultdict(list)

        for key, value in tags.items():
            if should_skip_key(key):
                continue

            new_key = KEY_RENAMES.get(key, key)
            new_value = normalize_value(new_key, value)

            if new_key != key or new_value != value:
                candidates_by_key[new_key].append({
                    "old_key": key,
                    "old_value": value,
                    "new_key": new_key,
                    "new_value": new_value,
                })

        rows = []

        for new_key, candidates in sorted(candidates_by_key.items()):
            existing_new_value = tags.get(new_key, "")
            existing_final_value = (
                normalize_value(new_key, existing_new_value)
                if new_key in tags
                else None
            )
            new_values = {candidate["new_value"] for candidate in candidates}
            if existing_final_value is not None:
                new_values.add(existing_final_value)

            old_keys_to_remove = sorted({
                candidate["old_key"]
                for candidate in candidates
                if candidate["old_key"] != candidate["new_key"]
            })

            if len(new_values) > 1:
                rows.append(self.build_row(
                    service=service,
                    resource_type=resource_type,
                    arn=arn,
                    status="skipped_conflict",
                    action="review_required",
                    old_key=" | ".join(candidate["old_key"] for candidate in candidates),
                    old_value=" | ".join(candidate["old_value"] for candidate in candidates),
                    new_key=new_key,
                    new_value=" | ".join(sorted(new_values)),
                    remove_keys=",".join(old_keys_to_remove),
                    existing_new_value=existing_new_value,
                    reason="varios valores finales distintos para la misma key",
                    applied=False,
                ))
                continue

            new_value = next(iter(new_values))
            apply_tag = existing_new_value != new_value

            if not apply_tag and not old_keys_to_remove:
                continue

            actions = []
            if apply_tag:
                actions.append("tag")
            if old_keys_to_remove:
                actions.append("untag_old_keys")

            rows.append(self.build_row(
                service=service,
                resource_type=resource_type,
                arn=arn,
                status="planned",
                action="+".join(actions),
                old_key=" | ".join(candidate["old_key"] for candidate in candidates),
                old_value=" | ".join(candidate["old_value"] for candidate in candidates),
                new_key=new_key,
                new_value=new_value,
                remove_keys=",".join(old_keys_to_remove),
                existing_new_value=existing_new_value,
                reason="",
                applied=False,
            ))

        return rows

    def apply_row(self, row):
        if row["status"] != "planned":
            return row

        arn = row["arn"]
        tags_to_apply = {}
        keys_to_remove = parse_csv_list(row["remove_keys"])
        actions = set(parse_csv_list(row["action"].replace("+", ",")))

        if "tag" in actions:
            tags_to_apply[row["new_key"]] = row["new_value"]

        try:
            if tags_to_apply:
                self.client.tag_resources(
                    ResourceARNList=[arn],
                    Tags=tags_to_apply,
                )

            if keys_to_remove:
                self.client.untag_resources(
                    ResourceARNList=[arn],
                    TagKeys=keys_to_remove,
                )

            row["status"] = "applied"
            row["applied"] = True
            return row
        except Exception as exc:
            row["status"] = "error"
            row["reason"] = str(exc)
            row["applied"] = False
            return row

    def build_row(
        self,
        service,
        resource_type,
        arn,
        status,
        action,
        old_key,
        old_value,
        new_key,
        new_value,
        remove_keys,
        existing_new_value,
        reason,
        applied,
    ):
        return {
            "region": self.region,
            "service": service,
            "resource_type": resource_type,
            "arn": arn,
            "status": status,
            "action": action,
            "old_key": old_key,
            "old_value": old_value,
            "new_key": new_key,
            "new_value": new_value,
            "remove_keys": remove_keys,
            "existing_new_value": existing_new_value,
            "reason": reason,
            "applied": applied,
        }


def parse_arn(arn: str):
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


def should_skip_key(key: str):
    return key.startswith(SKIP_KEY_PREFIXES)


def normalize_value(key: str, value: str):
    return VALUE_REPLACEMENTS.get(key, {}).get(value, value)


def parse_csv_list(value: str):
    if not value:
        return []
    return [item for item in value.split(",") if item]


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
    path = os.path.join(OUT_DIR, f"aws_tag_cleaner_{suffix}_{timestamp}.csv")

    with open(path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "region",
            "service",
            "resource_type",
            "arn",
            "status",
            "action",
            "old_key",
            "old_value",
            "new_key",
            "new_value",
            "remove_keys",
            "existing_new_value",
            "reason",
            "applied",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return path


def print_summary(rows, report_path, apply_changes):
    planned = sum(1 for row in rows if row["status"] == "planned")
    applied = sum(1 for row in rows if row["status"] == "applied")
    conflicts = sum(1 for row in rows if row["status"] == "skipped_conflict")
    errors = sum(1 for row in rows if row["status"] == "error")

    print()
    print(f"Cambios detectados: {len(rows)}")
    print(f"Planificados: {planned}")
    print(f"Aplicados: {applied}")
    print(f"Conflictos: {conflicts}")
    print(f"Errores: {errors}")
    print(f"Modo aplicar: {apply_changes}")
    print(f"Informe generado: {report_path}")


def main():
    apply_changes = ask_apply()
    rows = []

    for region in REGIONS:
        region = region.strip()
        if not region:
            continue

        print(f"Revisando region: {region}")
        cleaner = AwsTagCleaner(region)

        for resource in cleaner.get_all_resources():
            resource_rows = cleaner.build_resource_plan(resource)

            if apply_changes:
                resource_rows = [cleaner.apply_row(row) for row in resource_rows]

            rows.extend(resource_rows)

            for row in resource_rows:
                print(f"{row['status']}: {row['arn']}")
                print(
                    f"  {row['old_key']}={row['old_value']} -> "
                    f"{row['new_key']}={row['new_value']}"
                )
                if row["remove_keys"]:
                    print(f"  borrar keys: {row['remove_keys']}")
                if row["reason"]:
                    print(f"  motivo: {row['reason']}")

    report_path = write_report(rows, apply_changes)
    print_summary(rows, report_path, apply_changes)


if __name__ == "__main__":
    main()
