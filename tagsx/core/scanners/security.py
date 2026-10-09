"""Scanners de seguridad: secretsmanager, acm, kms, iam, access-analyzer,
guardduty."""

from .common import emit


def scan_untagged_secretsmanager(sesion, region, account, seen_arns):
    client = sesion.client("secretsmanager", region_name=region)
    paginator = client.get_paginator("list_secrets")
    for page in paginator.paginate():
        for secret in page.get("SecretList", []):
            item = emit(secret["ARN"], seen_arns)
            if item:
                yield item


def scan_untagged_acm(sesion, region, account, seen_arns):
    client = sesion.client("acm", region_name=region)
    paginator = client.get_paginator("list_certificates")
    for page in paginator.paginate():
        for cert in page.get("CertificateSummaryList", []):
            item = emit(cert["CertificateArn"], seen_arns)
            if item:
                yield item


def scan_untagged_kms(sesion, region, account, seen_arns):
    # Las claves gestionadas por AWS (alias/aws/...) no se pueden etiquetar: fuera.
    client = sesion.client("kms", region_name=region)
    paginator = client.get_paginator("list_keys")
    for page in paginator.paginate():
        for key in page.get("Keys", []):
            if key["KeyArn"] in seen_arns:
                continue
            try:
                metadata = client.describe_key(KeyId=key["KeyId"])["KeyMetadata"]
                if metadata.get("KeyManager") == "AWS":
                    continue
            except Exception:
                pass
            item = emit(key["KeyArn"], seen_arns)
            if item:
                yield item


def scan_untagged_iam(sesion, region, account, seen_arns):
    # IAM es global: se llama con la region global (us-east-1).
    client = sesion.client("iam", region_name=region)
    for method, list_key, params in [
        ("list_roles", "Roles", None),
        ("list_users", "Users", None),
        ("list_policies", "Policies", {"Scope": "Local"}),
    ]:
        paginator = client.get_paginator(method)
        for page in paginator.paginate(**(params or {})):
            for entry in page.get(list_key, []):
                item = emit(entry["Arn"], seen_arns)
                if item:
                    yield item


def scan_untagged_access_analyzer(sesion, region, account, seen_arns):
    client = sesion.client("accessanalyzer", region_name=region)
    paginator = client.get_paginator("list_analyzers")
    for page in paginator.paginate():
        for analyzer in page.get("analyzers", []):
            item = emit(analyzer["arn"], seen_arns)
            if item:
                yield item


def scan_untagged_guardduty(sesion, region, account, seen_arns):
    client = sesion.client("guardduty", region_name=region)
    paginator = client.get_paginator("list_detectors")
    for page in paginator.paginate():
        for detector_id in page.get("DetectorIds", []):
            item = emit(f"arn:aws:guardduty:{region}:{account}:detector/{detector_id}", seen_arns)
            if item:
                yield item


SCANNERS = {
    "secretsmanager": scan_untagged_secretsmanager,
    "acm": scan_untagged_acm,
    "kms": scan_untagged_kms,
    "iam": scan_untagged_iam,
    "access-analyzer": scan_untagged_access_analyzer,
    "guardduty": scan_untagged_guardduty,
}
