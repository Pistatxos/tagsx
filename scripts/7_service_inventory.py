#!/usr/bin/env python3
"""
Inventario completo de recursos AWS con sus tags actuales.

Genera un CSV con una fila por recurso: nombre, servicio, arn, url (enlace a
la consola de AWS cuando se puede construir de forma fiable) y una columna
por cada tag del esquema objetivo. Solo lectura: no modifica nada en AWS.

La url solo se rellena para los servicios/resource_type mas comunes donde el
formato de la consola es estable; el resto se deja en blanco antes que dar un
enlace que pueda ser incorrecto.
"""
import csv
import os
import urllib.parse
from datetime import datetime

import boto3


REGIONS = os.getenv("AWS_REGIONS", "eu-south-2").split(",")
OUT_DIR = os.getenv("OUT_DIR", "exports")

SCHEMA_TAGS = [
    "Name",
    "Application",
    "Environment",
    "Owner",
    "Project",
    "Product",
    "Service",
    "Component",
    "ManagedBy",
]

SKIP_KEY_PREFIXES = ("aws:", "kubernetes.io/")


def get_all_resources(client):
    paginator = client.get_paginator("get_resources")
    for page in paginator.paginate(ResourcesPerPage=100):
        for item in page.get("ResourceTagMappingList", []):
            yield item


def parse_arn(arn):
    parts = arn.split(":", 5)
    service = parts[2] if len(parts) > 2 else ""
    region = parts[3] if len(parts) > 3 else ""
    account = parts[4] if len(parts) > 4 else ""
    resource = parts[5] if len(parts) > 5 else ""
    resource = resource.lstrip("/")

    if "/" in resource:
        resource_type, resource_id = resource.split("/", 1)
    elif ":" in resource:
        resource_type, resource_id = resource.split(":", 1)
    else:
        resource_type, resource_id = resource, resource

    return service, resource_type, resource_id, region, account


def friendly_name(resource_id):
    return resource_id.rstrip("/").split("/")[-1]


def build_url(service, resource_type, resource_id, arn, region, account=""):
    enc_arn = urllib.parse.quote(arn, safe="")
    base = f"https://{region}.console.aws.amazon.com"

    if service == "ec2":
        if resource_type == "instance":
            return f"{base}/ec2/home?region={region}#InstanceDetails:instanceId={resource_id}"
        if resource_type == "security-group":
            return f"{base}/ec2/home?region={region}#SecurityGroup:securityGroupId={resource_id}"
        if resource_type == "volume":
            return f"{base}/ec2/home?region={region}#VolumeDetails:volumeId={resource_id}"
        if resource_type == "snapshot":
            return f"{base}/ec2/home?region={region}#SnapshotDetails:snapshotId={resource_id}"
        if resource_type == "network-interface":
            return f"{base}/ec2/home?region={region}#NetworkInterfaceDetails:networkInterfaceId={resource_id}"
        if resource_type == "elastic-ip":
            return f"{base}/ec2/home?region={region}#Addresses:search={resource_id}"
        if resource_type == "subnet":
            return f"{base}/vpcconsole/home?region={region}#SubnetDetails:subnetId={resource_id}"
        if resource_type == "route-table":
            return f"{base}/vpcconsole/home?region={region}#RouteTableDetails:routeTableId={resource_id}"
        if resource_type == "vpc":
            return f"{base}/vpcconsole/home?region={region}#VpcDetails:VpcId={resource_id}"
        if resource_type == "vpc-endpoint":
            return f"{base}/vpcconsole/home?region={region}#EndpointDetails:vpcEndpointId={resource_id}"
        if resource_type == "internet-gateway":
            return f"{base}/vpcconsole/home?region={region}#igws:search={resource_id}"
        return ""

    if service == "lambda" and resource_type == "function":
        return f"{base}/lambda/home?region={region}#/functions/{friendly_name(resource_id)}"

    if service == "rds":
        if resource_type == "cluster":
            return f"{base}/rds/home?region={region}#database:id={friendly_name(resource_id)};is-cluster=true"
        if resource_type == "db":
            return f"{base}/rds/home?region={region}#database:id={friendly_name(resource_id)};is-cluster=false"
        return ""

    if service == "s3":
        return f"{base}/s3/buckets/{resource_type}?region={region}"

    if service == "apigateway" and resource_type == "restapis":
        api_id = resource_id.split("/", 1)[0]
        return f"{base}/apigateway/home?region={region}#/apis/{api_id}/resources"

    if service == "sns" and resource_type:
        return f"{base}/sns/v3/home?region={region}#/topic/{enc_arn}"

    if service == "sqs" and resource_type and account:
        queue_name = friendly_name(resource_id)
        queue_url = f"https://sqs.{region}.amazonaws.com/{account}/{queue_name}"
        return f"{base}/sqs/v2/home?region={region}#/queues/{urllib.parse.quote(queue_url, safe='')}"

    if service == "cloudwatch" and resource_type == "alarm":
        return f"{base}/cloudwatch/home?region={region}#alarmsV2:alarm/{urllib.parse.quote(friendly_name(resource_id))}"

    if service == "cloudformation" and resource_type == "stack":
        return f"{base}/cloudformation/home?region={region}#/stacks/stackinfo?stackId={enc_arn}"

    if service == "glue" and resource_type == "crawler":
        return f"{base}/glue/home?region={region}#/v2/data-catalog/crawlers/view/{friendly_name(resource_id)}"

    if service == "sagemaker" and resource_type == "notebook-instance":
        return f"{base}/sagemaker/home?region={region}#/notebook-instances/{friendly_name(resource_id)}"

    if service == "transfer" and resource_type == "server":
        return f"{base}/transfer/home?region={region}#/servers/{friendly_name(resource_id)}/details"

    if service == "cloudtrail" and resource_type == "trail":
        return f"{base}/cloudtrail/home?region={region}#/trails/{enc_arn}"

    if service == "access-analyzer" and resource_type == "analyzer":
        return f"{base}/access-analyzer/home?region={region}#/analyzer/{friendly_name(resource_id)}"

    if service == "elasticloadbalancing":
        return f"{base}/ec2/home?region={region}#LoadBalancer:loadBalancerArn={enc_arn}"

    if service == "ssm" and resource_type == "parameter":
        path = resource_id if resource_id.startswith("/") else "/" + resource_id
        return f"{base}/systems-manager/parameters{path}/description?region={region}"

    return ""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(OUT_DIR, f"aws_service_inventory_{timestamp}.csv")

    rows = []
    for region in REGIONS:
        region = region.strip()
        if not region:
            continue

        print(f"Escaneando region: {region}")
        client = boto3.client("resourcegroupstaggingapi", region_name=region)

        for resource in get_all_resources(client):
            arn = resource["ResourceARN"]
            service, resource_type, resource_id, arn_region, account = parse_arn(arn)
            tags = {
                tag["Key"]: tag["Value"]
                for tag in resource.get("Tags", [])
                if not tag["Key"].startswith(SKIP_KEY_PREFIXES)
            }

            row = {
                "nombre": tags.get("Name") or friendly_name(resource_id),
                "servicio": service,
                "arn": arn,
                "url": build_url(service, resource_type, resource_id, arn, arn_region or region, account),
            }
            for tag_key in SCHEMA_TAGS:
                row[tag_key] = tags.get(tag_key, "")

            rows.append(row)

    fieldnames = ["nombre", "servicio", "arn", "url"] + SCHEMA_TAGS
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"Total recursos: {len(rows)}")
    print(f"Inventario generado: {report_path}")


if __name__ == "__main__":
    main()
