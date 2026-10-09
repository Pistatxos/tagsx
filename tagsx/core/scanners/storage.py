"""Scanners de almacenamiento y datos: s3, efs, glue, backup."""

from .common import emit


def region_bucket(client, nombre):
    """La región de un bucket. get_bucket_location devuelve None para us-east-1 y
    "EU" para los muy antiguos de eu-west-1."""
    location = client.get_bucket_location(Bucket=nombre).get("LocationConstraint")
    return {None: "us-east-1", "": "us-east-1", "EU": "eu-west-1"}.get(location, location)


def scan_untagged_s3(sesion, region, account, seen_arns):
    # S3 es global para listar, pero cada bucket se etiqueta en su region: el ARN no
    # la lleva, asi que se guarda aparte. list_buckets ya trae BucketRegion; si no
    # (versiones antiguas), se pregunta bucket a bucket.
    client = sesion.client("s3", region_name=region)
    for bucket in client.list_buckets().get("Buckets", []):
        arn = f"arn:aws:s3:::{bucket['Name']}"
        if arn in seen_arns:
            continue
        bucket_region = bucket.get("BucketRegion")
        if not bucket_region:
            try:
                bucket_region = region_bucket(client, bucket["Name"])
            except Exception:
                bucket_region = None
        item = emit(arn, seen_arns, region=bucket_region)
        if item:
            yield item


def scan_untagged_efs(sesion, region, account, seen_arns):
    client = sesion.client("efs", region_name=region)
    paginator = client.get_paginator("describe_file_systems")
    for page in paginator.paginate():
        for fs in page.get("FileSystems", []):
            arn = fs.get("FileSystemArn") or f"arn:aws:elasticfilesystem:{region}:{account}:file-system/{fs['FileSystemId']}"
            item = emit(arn, seen_arns)
            if item:
                yield item


def scan_untagged_glue(sesion, region, account, seen_arns):
    client = sesion.client("glue", region_name=region)
    paginator = client.get_paginator("get_crawlers")
    for page in paginator.paginate():
        for crawler in page.get("Crawlers", []):
            item = emit(f"arn:aws:glue:{region}:{account}:crawler/{crawler['Name']}", seen_arns)
            if item:
                yield item


def scan_untagged_backup(sesion, region, account, seen_arns):
    client = sesion.client("backup", region_name=region)
    paginator = client.get_paginator("list_backup_vaults")
    for page in paginator.paginate():
        for vault in page.get("BackupVaultList", []):
            item = emit(vault["BackupVaultArn"], seen_arns)
            if item:
                yield item


SCANNERS = {
    "s3": scan_untagged_s3,
    "efs": scan_untagged_efs,
    "glue": scan_untagged_glue,
    "backup": scan_untagged_backup,
}
