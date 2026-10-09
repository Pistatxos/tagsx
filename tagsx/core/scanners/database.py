"""Scanners de bases de datos: rds, dynamodb, elasticache, redshift."""

from .common import emit


def scan_untagged_rds(sesion, region, account, seen_arns):
    client = sesion.client("rds", region_name=region)
    for method, list_key, arn_field in [
        ("describe_db_instances", "DBInstances", "DBInstanceArn"),
        ("describe_db_clusters", "DBClusters", "DBClusterArn"),
    ]:
        paginator = client.get_paginator(method)
        for page in paginator.paginate():
            for entry in page.get(list_key, []):
                item = emit(entry[arn_field], seen_arns)
                if item:
                    yield item


def scan_untagged_dynamodb(sesion, region, account, seen_arns):
    client = sesion.client("dynamodb", region_name=region)
    paginator = client.get_paginator("list_tables")
    for page in paginator.paginate():
        for name in page.get("TableNames", []):
            item = emit(f"arn:aws:dynamodb:{region}:{account}:table/{name}", seen_arns)
            if item:
                yield item


def scan_untagged_elasticache(sesion, region, account, seen_arns):
    client = sesion.client("elasticache", region_name=region)
    paginator = client.get_paginator("describe_cache_clusters")
    for page in paginator.paginate():
        for cluster in page.get("CacheClusters", []):
            item = emit(cluster["ARN"], seen_arns)
            if item:
                yield item


def scan_untagged_redshift(sesion, region, account, seen_arns):
    client = sesion.client("redshift", region_name=region)
    paginator = client.get_paginator("describe_clusters")
    for page in paginator.paginate():
        for cluster in page.get("Clusters", []):
            arn = f"arn:aws:redshift:{region}:{account}:cluster:{cluster['ClusterIdentifier']}"
            item = emit(arn, seen_arns)
            if item:
                yield item


SCANNERS = {
    "rds": scan_untagged_rds,
    "dynamodb": scan_untagged_dynamodb,
    "elasticache": scan_untagged_elasticache,
    "redshift": scan_untagged_redshift,
}
