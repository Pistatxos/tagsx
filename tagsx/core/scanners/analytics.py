"""Scanners de analitica/datos en streaming: athena, kinesis, firehose."""

from .common import emit


def scan_untagged_athena(sesion, region, account, seen_arns):
    # boto3 no define paginador para list_work_groups, hay que paginar a mano.
    client = sesion.client("athena", region_name=region)
    next_token = None
    while True:
        kwargs = {"NextToken": next_token} if next_token else {}
        page = client.list_work_groups(**kwargs)
        for wg in page.get("WorkGroups", []):
            item = emit(f"arn:aws:athena:{region}:{account}:workgroup/{wg['Name']}", seen_arns)
            if item:
                yield item
        next_token = page.get("NextToken")
        if not next_token:
            break


def scan_untagged_kinesis(sesion, region, account, seen_arns):
    client = sesion.client("kinesis", region_name=region)
    paginator = client.get_paginator("list_streams")
    for page in paginator.paginate():
        for name in page.get("StreamNames", []):
            item = emit(f"arn:aws:kinesis:{region}:{account}:stream/{name}", seen_arns)
            if item:
                yield item


def scan_untagged_firehose(sesion, region, account, seen_arns):
    client = sesion.client("firehose", region_name=region)
    names = client.list_delivery_streams().get("DeliveryStreamNames", [])
    for name in names:
        item = emit(f"arn:aws:firehose:{region}:{account}:deliverystream/{name}", seen_arns)
        if item:
            yield item


SCANNERS = {
    "athena": scan_untagged_athena,
    "kinesis": scan_untagged_kinesis,
    "firehose": scan_untagged_firehose,
}
