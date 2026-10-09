"""Scanners de observabilidad: cloudwatch, cloudtrail."""

from .common import emit


def scan_untagged_cloudwatch(sesion, region, account, seen_arns):
    client = sesion.client("cloudwatch", region_name=region)
    next_token = None
    while True:
        kwargs = {"NextToken": next_token} if next_token else {}
        page = client.describe_alarms(**kwargs)
        for alarm in page.get("MetricAlarms", []) + page.get("CompositeAlarms", []):
            item = emit(alarm["AlarmArn"], seen_arns)
            if item:
                yield item
        next_token = page.get("NextToken")
        if not next_token:
            break


def scan_untagged_cloudtrail(sesion, region, account, seen_arns):
    client = sesion.client("cloudtrail", region_name=region)
    # describe_trails no tiene paginador, devuelve todo de golpe.
    for trail in client.describe_trails().get("trailList", []):
        item = emit(trail["TrailARN"], seen_arns)
        if item:
            yield item


SCANNERS = {
    "cloudwatch": scan_untagged_cloudwatch,
    "cloudtrail": scan_untagged_cloudtrail,
}
