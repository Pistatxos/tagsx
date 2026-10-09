#!/usr/bin/env python3
"""
Auditoria de tags AWS.

Genera un unico CSV detallado con una fila por tag encontrada:
  region, service, resource_type, arn, tag_key, tag_value

Tambien muestra en consola resumen por key y por key/value.
"""
import csv
import os
from collections import Counter
from datetime import datetime

import boto3


REGIONS = os.getenv("AWS_REGIONS", "eu-south-2").split(",")
OUT_DIR = os.getenv("OUT_DIR", "exports")

SKIP_KEY_PREFIXES = (
    "aws:",
    "kubernetes.io/",
)


def get_all_resources(client):
    paginator = client.get_paginator("get_resources")
    for page in paginator.paginate(ResourcesPerPage=100):
        for item in page.get("ResourceTagMappingList", []):
            yield item


def parse_arn(arn: str):
    parts = arn.split(":", 5)
    service = parts[2] if len(parts) > 2 else ""
    resource = parts[5] if len(parts) > 5 else ""

    if "/" in resource:
        resource_type = resource.split("/", 1)[0]
    elif ":" in resource:
        resource_type = resource.split(":", 1)[0]
    else:
        resource_type = resource

    return service, resource_type


def should_skip_key(key: str):
    return key.startswith(SKIP_KEY_PREFIXES)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(OUT_DIR, f"aws_tags_audit_{timestamp}.csv")

    rows = []
    key_counts = Counter()
    key_value_counts = Counter()
    resource_count = 0

    for region in REGIONS:
        region = region.strip()
        if not region:
            continue

        print(f"Auditando region: {region}")
        client = boto3.client("resourcegroupstaggingapi", region_name=region)

        for resource in get_all_resources(client):
            resource_count += 1
            arn = resource["ResourceARN"]
            service, resource_type = parse_arn(arn)

            for tag in resource.get("Tags", []):
                key = tag["Key"]
                value = tag["Value"]

                if should_skip_key(key):
                    continue

                rows.append({
                    "region": region,
                    "service": service,
                    "resource_type": resource_type,
                    "arn": arn,
                    "tag_key": key,
                    "tag_value": value,
                })
                key_counts[key] += 1
                key_value_counts[(key, value)] += 1

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "region",
            "service",
            "resource_type",
            "arn",
            "tag_key",
            "tag_value",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"Total recursos escaneados: {resource_count}")
    print(f"Total tags auditadas: {len(rows)}")
    print(f"Total keys distintas: {len(key_counts)}")

    print()
    print("Resumen por tag key")
    print(f"{'KEY':<30} {'COUNT':>6}")
    print("-" * 40)
    for key, count in key_counts.most_common():
        print(f"{key:<30} {count:>6}")

    print()
    print("Resumen por tag key/value")
    print(f"{'KEY':<30} {'VALUE':<40} {'COUNT':>6}")
    print("-" * 82)
    for (key, value), count in key_value_counts.most_common():
        print(f"{key:<30} {value:<40} {count:>6}")

    print()
    print(f"CSV auditoria: {report_path}")


if __name__ == "__main__":
    main()
