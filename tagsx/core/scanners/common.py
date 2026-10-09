"""Helper compartido por todos los escáneres."""


def emit(arn, seen_arns, region=None):
    """Devuelve un item de recurso "sin tag" listo para el inventario, o
    None si ese ARN ya se habia visto (evita duplicados con lo que ya
    encontro resourcegroupstaggingapi). `region` solo hace falta cuando el
    ARN no la lleva y no es global (un bucket de S3)."""
    if arn in seen_arns:
        return None
    seen_arns.add(arn)
    item = {"ResourceARN": arn, "Tags": []}
    if region:
        item["Region"] = region
    return item
