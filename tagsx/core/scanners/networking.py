"""Scanners de red y entrega: apigateway (REST y HTTP/WebSocket), route53,
cloudfront, elasticloadbalancing, transfer, wafv2."""

from .common import emit


def scan_untagged_apigateway(sesion, region, account, seen_arns):
    client = sesion.client("apigateway", region_name=region)
    paginator = client.get_paginator("get_rest_apis")
    for page in paginator.paginate():
        for api in page.get("items", []):
            item = emit(f"arn:aws:apigateway:{region}::/restapis/{api['id']}", seen_arns)
            if item:
                yield item


def scan_untagged_apigatewayv2(sesion, region, account, seen_arns):
    # APIs HTTP y WebSocket: get_apis no tiene paginador en boto3.
    client = sesion.client("apigatewayv2", region_name=region)
    next_token = None
    while True:
        kwargs = {"NextToken": next_token} if next_token else {}
        page = client.get_apis(**kwargs)
        for api in page.get("Items", []):
            item = emit(f"arn:aws:apigateway:{region}::/apis/{api['ApiId']}", seen_arns)
            if item:
                yield item
        next_token = page.get("NextToken")
        if not next_token:
            break


def _scan_wafv2(sesion, region, seen_arns, scope):
    client = sesion.client("wafv2", region_name=region)
    for method, list_key in [
        ("list_web_acls", "WebACLs"),
        ("list_rule_groups", "RuleGroups"),
        ("list_ip_sets", "IPSets"),
        ("list_regex_pattern_sets", "RegexPatternSets"),
    ]:
        marker = None
        while True:
            kwargs = {"Scope": scope, "Limit": 100}
            if marker:
                kwargs["NextMarker"] = marker
            page = getattr(client, method)(**kwargs)
            for entry in page.get(list_key, []):
                item = emit(entry["ARN"], seen_arns)
                if item:
                    yield item
            marker = page.get("NextMarker")
            if not marker or not page.get(list_key):
                break


def scan_untagged_wafv2(sesion, region, account, seen_arns):
    # WAF necesita Scope: aqui lo REGIONAL (ALB, API Gateway...) de cada region.
    yield from _scan_wafv2(sesion, region, seen_arns, "REGIONAL")


def scan_untagged_wafv2_cloudfront(sesion, region, account, seen_arns):
    # Lo de CloudFront es global y solo se lista desde us-east-1.
    yield from _scan_wafv2(sesion, "us-east-1", seen_arns, "CLOUDFRONT")


def scan_untagged_route53(sesion, region, account, seen_arns):
    # Route53 es global.
    client = sesion.client("route53", region_name=region)
    paginator = client.get_paginator("list_hosted_zones")
    for page in paginator.paginate():
        for zone in page.get("HostedZones", []):
            zone_id = zone["Id"].split("/")[-1]
            item = emit(f"arn:aws:route53:::hostedzone/{zone_id}", seen_arns)
            if item:
                yield item


def scan_untagged_cloudfront(sesion, region, account, seen_arns):
    # CloudFront es global.
    client = sesion.client("cloudfront", region_name=region)
    paginator = client.get_paginator("list_distributions")
    for page in paginator.paginate():
        items = page.get("DistributionList", {}).get("Items", [])
        for dist in items:
            item = emit(dist["ARN"], seen_arns)
            if item:
                yield item


def scan_untagged_elasticloadbalancing(sesion, region, account, seen_arns):
    client = sesion.client("elbv2", region_name=region)
    paginator = client.get_paginator("describe_load_balancers")
    for page in paginator.paginate():
        for lb in page.get("LoadBalancers", []):
            item = emit(lb["LoadBalancerArn"], seen_arns)
            if item:
                yield item


def scan_untagged_transfer(sesion, region, account, seen_arns):
    client = sesion.client("transfer", region_name=region)
    paginator = client.get_paginator("list_servers")
    for page in paginator.paginate():
        for server in page.get("Servers", []):
            item = emit(server["Arn"], seen_arns)
            if item:
                yield item


SCANNERS = {
    "apigateway": scan_untagged_apigateway,
    "apigatewayv2": scan_untagged_apigatewayv2,
    "route53": scan_untagged_route53,
    "cloudfront": scan_untagged_cloudfront,
    "elasticloadbalancing": scan_untagged_elasticloadbalancing,
    "transfer": scan_untagged_transfer,
    "wafv2": scan_untagged_wafv2,
}

# Lo que ademas tiene una parte global, que se escanea una sola vez en us-east-1
SCANNERS_GLOBALES_EXTRA = {
    "wafv2": scan_untagged_wafv2_cloudfront,
}
