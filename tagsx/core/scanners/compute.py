"""Scanners de servicios de compute: ec2, lambda, ecs, eks, sagemaker."""

from .common import emit


def scan_untagged_ec2(sesion, region, account, seen_arns):
    client = sesion.client("ec2", region_name=region)

    specs = [
        ("describe_instances", None, lambda page: (
            i["InstanceId"]
            for r in page.get("Reservations", [])
            for i in r.get("Instances", [])
        ), "instance"),
        ("describe_security_groups", None, lambda page: (g["GroupId"] for g in page.get("SecurityGroups", [])), "security-group"),
        ("describe_vpcs", None, lambda page: (v["VpcId"] for v in page.get("Vpcs", [])), "vpc"),
        ("describe_subnets", None, lambda page: (s["SubnetId"] for s in page.get("Subnets", [])), "subnet"),
        ("describe_route_tables", None, lambda page: (t["RouteTableId"] for t in page.get("RouteTables", [])), "route-table"),
        ("describe_volumes", None, lambda page: (v["VolumeId"] for v in page.get("Volumes", [])), "volume"),
        ("describe_snapshots", {"OwnerIds": ["self"]}, lambda page: (s["SnapshotId"] for s in page.get("Snapshots", [])), "snapshot"),
        ("describe_internet_gateways", None, lambda page: (g["InternetGatewayId"] for g in page.get("InternetGateways", [])), "internet-gateway"),
        ("describe_vpc_endpoints", None, lambda page: (e["VpcEndpointId"] for e in page.get("VpcEndpoints", [])), "vpc-endpoint"),
        ("describe_network_interfaces", None, lambda page: (n["NetworkInterfaceId"] for n in page.get("NetworkInterfaces", [])), "network-interface"),
    ]

    for method, params, extract_ids, resource_type in specs:
        paginator = client.get_paginator(method)
        for page in paginator.paginate(**(params or {})):
            for rid in extract_ids(page):
                item = emit(f"arn:aws:ec2:{region}:{account}:{resource_type}/{rid}", seen_arns)
                if item:
                    yield item

    # describe_addresses no tiene paginador (siempre devuelve todo de golpe).
    for addr in client.describe_addresses().get("Addresses", []):
        allocation_id = addr.get("AllocationId")
        if allocation_id:
            item = emit(f"arn:aws:ec2:{region}:{account}:elastic-ip/{allocation_id}", seen_arns)
            if item:
                yield item


def scan_untagged_lambda(sesion, region, account, seen_arns):
    client = sesion.client("lambda", region_name=region)
    paginator = client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page.get("Functions", []):
            item = emit(fn["FunctionArn"], seen_arns)
            if item:
                yield item


def scan_untagged_ecs(sesion, region, account, seen_arns):
    client = sesion.client("ecs", region_name=region)
    paginator = client.get_paginator("list_clusters")
    for page in paginator.paginate():
        for arn in page.get("clusterArns", []):
            item = emit(arn, seen_arns)
            if item:
                yield item


def scan_untagged_eks(sesion, region, account, seen_arns):
    client = sesion.client("eks", region_name=region)
    paginator = client.get_paginator("list_clusters")
    for page in paginator.paginate():
        for name in page.get("clusters", []):
            item = emit(f"arn:aws:eks:{region}:{account}:cluster/{name}", seen_arns)
            if item:
                yield item


def scan_untagged_sagemaker(sesion, region, account, seen_arns):
    client = sesion.client("sagemaker", region_name=region)
    paginator = client.get_paginator("list_notebook_instances")
    for page in paginator.paginate():
        for nb in page.get("NotebookInstances", []):
            item = emit(nb["NotebookInstanceArn"], seen_arns)
            if item:
                yield item


SCANNERS = {
    "ec2": scan_untagged_ec2,
    "lambda": scan_untagged_lambda,
    "ecs": scan_untagged_ecs,
    "eks": scan_untagged_eks,
    "sagemaker": scan_untagged_sagemaker,
}
