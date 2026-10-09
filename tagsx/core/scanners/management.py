"""Scanners de gestion de cuenta: ssm, organizations, scheduler."""
from botocore.config import Config

from .common import emit

# DescribeParameters tiene un limite de peticiones/segundo bajo por defecto
# (mas bajo aun si la cuenta no tiene activado el "high-throughput" de
# Parameter Store) y con muchos parametros se agota facilmente el retry por
# defecto de boto3. "adaptive" ajusta el ritmo de peticiones solo en
# respuesta a los ThrottlingException, en vez de fallar a las pocas.
_SSM_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 10})


def scan_untagged_ssm(sesion, region, account, seen_arns):
    client = sesion.client("ssm", region_name=region, config=_SSM_RETRY_CONFIG)
    paginator = client.get_paginator("describe_parameters")
    for page in paginator.paginate():
        for param in page.get("Parameters", []):
            name = param["Name"].lstrip("/")
            item = emit(f"arn:aws:ssm:{region}:{account}:parameter/{name}", seen_arns)
            if item:
                yield item


def scan_untagged_organizations(sesion, region, account, seen_arns):
    # Organizations es global y solo responde desde la cuenta de gestion.
    client = sesion.client("organizations", region_name=region)
    paginator = client.get_paginator("list_accounts")
    for page in paginator.paginate():
        for acc in page.get("Accounts", []):
            item = emit(acc["Arn"], seen_arns)
            if item:
                yield item


def scan_untagged_scheduler(sesion, region, account, seen_arns):
    client = sesion.client("scheduler", region_name=region)
    paginator = client.get_paginator("list_schedules")
    for page in paginator.paginate():
        for schedule in page.get("Schedules", []):
            item = emit(schedule["Arn"], seen_arns)
            if item:
                yield item


SCANNERS = {
    "ssm": scan_untagged_ssm,
    "organizations": scan_untagged_organizations,
    "scheduler": scan_untagged_scheduler,
}
