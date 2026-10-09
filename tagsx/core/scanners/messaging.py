"""Scanners de mensajeria/eventos: sns, sqs, events."""

from .common import emit


def scan_untagged_sns(sesion, region, account, seen_arns):
    client = sesion.client("sns", region_name=region)
    paginator = client.get_paginator("list_topics")
    for page in paginator.paginate():
        for topic in page.get("Topics", []):
            item = emit(topic["TopicArn"], seen_arns)
            if item:
                yield item


def scan_untagged_sqs(sesion, region, account, seen_arns):
    client = sesion.client("sqs", region_name=region)
    paginator = client.get_paginator("list_queues")
    for page in paginator.paginate():
        for queue_url in page.get("QueueUrls", []):
            name = queue_url.rstrip("/").split("/")[-1]
            item = emit(f"arn:aws:sqs:{region}:{account}:{name}", seen_arns)
            if item:
                yield item


def scan_untagged_events(sesion, region, account, seen_arns):
    client = sesion.client("events", region_name=region)
    next_token = None
    while True:
        kwargs = {"NextToken": next_token} if next_token else {}
        page = client.list_rules(**kwargs)
        for rule in page.get("Rules", []):
            item = emit(rule["Arn"], seen_arns)
            if item:
                yield item
        next_token = page.get("NextToken")
        if not next_token:
            break


SCANNERS = {
    "sns": scan_untagged_sns,
    "sqs": scan_untagged_sqs,
    "events": scan_untagged_events,
}
