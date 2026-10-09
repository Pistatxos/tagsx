"""ARN: sus partes, el servicio «conceptual», la región donde se lee/etiqueta y el
enlace a la consola."""
import urllib.parse

# Lo global no tiene región en el ARN y la Tagging API lo lee y lo etiqueta en us-east-1.
# Si se usara la región por defecto, IAM/CloudFront/Route 53 salían «sin tags» y fallaban
# al aplicar.
REGION_GLOBAL = "us-east-1"
SERVICIOS_ARN_GLOBALES = {"iam", "cloudfront", "route53", "organizations", "waf"}


def parse_arn(arn):
    parts = arn.split(":", 5)
    service = parts[2] if len(parts) > 2 else ""
    region = parts[3] if len(parts) > 3 else ""
    account = parts[4] if len(parts) > 4 else ""
    resource = parts[5] if len(parts) > 5 else ""
    resource = resource.lstrip("/")

    if "/" in resource:
        resource_type, resource_id = resource.split("/", 1)
    elif ":" in resource:
        resource_type, resource_id = resource.split(":", 1)
    else:
        resource_type, resource_id = resource, resource

    return service, resource_type, resource_id, region, account


def normalizar_arn(arn):
    """El ARN tal como lo usa la Tagging API. describe_log_groups devuelve el log group
    con «:*» al final, y con él tag_resources no lo encuentra."""
    arn = (arn or "").strip()
    if arn.startswith("arn:") and ":logs:" in arn and ":log-group:" in arn and arn.endswith(":*"):
        return arn[:-2]
    return arn


def region_de(arn):
    """La región donde se opera con este ARN: la del ARN, us-east-1 para lo global o
    None si no se puede saber solo con el ARN (un bucket de S3: hay que preguntarlo)."""
    service, _, _, region, _ = parse_arn(arn)
    if region:
        return region
    if service in SERVICIOS_ARN_GLOBALES:
        return REGION_GLOBAL
    return None


def es_global(arn):
    service, _, _, region, _ = parse_arn(arn)
    return not region and service in SERVICIOS_ARN_GLOBALES


# Sub-recursos que viven bajo el namespace de ARN "ec2" pero son
# conceptualmente del servicio VPC (networking), no de EC2 compute.
VPC_RESOURCE_TYPES = {
    "vpc",
    "subnet",
    "route-table",
    "internet-gateway",
    "nat-gateway",
    "vpc-endpoint",
    "vpc-peering-connection",
    "security-group",
    "security-group-rule",
    "network-acl",
    "network-interface",
    "elastic-ip",
    "dhcp-options",
}


def classify_service(service, resource_type):
    if service == "ec2" and resource_type in VPC_RESOURCE_TYPES:
        return "vpc"
    if service == "apigateway" and resource_type == "apis":
        return "apigatewayv2"
    return service


def friendly_name(resource_id):
    return resource_id.rstrip("/").split("/")[-1]


def build_url(service, resource_type, resource_id, arn, region, account=""):
    enc_arn = urllib.parse.quote(arn, safe="")
    base = f"https://{region}.console.aws.amazon.com"

    if service == "ec2":
        if resource_type == "instance":
            return f"{base}/ec2/home?region={region}#InstanceDetails:instanceId={resource_id}"
        if resource_type == "security-group":
            return f"{base}/ec2/home?region={region}#SecurityGroup:securityGroupId={resource_id}"
        if resource_type == "volume":
            return f"{base}/ec2/home?region={region}#VolumeDetails:volumeId={resource_id}"
        if resource_type == "snapshot":
            return f"{base}/ec2/home?region={region}#SnapshotDetails:snapshotId={resource_id}"
        if resource_type == "network-interface":
            return f"{base}/ec2/home?region={region}#NetworkInterfaceDetails:networkInterfaceId={resource_id}"
        if resource_type == "elastic-ip":
            return f"{base}/ec2/home?region={region}#Addresses:search={resource_id}"
        if resource_type == "subnet":
            return f"{base}/vpcconsole/home?region={region}#SubnetDetails:subnetId={resource_id}"
        if resource_type == "route-table":
            return f"{base}/vpcconsole/home?region={region}#RouteTableDetails:routeTableId={resource_id}"
        if resource_type == "vpc":
            return f"{base}/vpcconsole/home?region={region}#VpcDetails:VpcId={resource_id}"
        if resource_type == "vpc-endpoint":
            return f"{base}/vpcconsole/home?region={region}#EndpointDetails:vpcEndpointId={resource_id}"
        if resource_type == "internet-gateway":
            return f"{base}/vpcconsole/home?region={region}#igws:search={resource_id}"
        return ""

    if service == "lambda" and resource_type == "function":
        return f"{base}/lambda/home?region={region}#/functions/{friendly_name(resource_id)}"

    if service == "rds":
        if resource_type == "cluster":
            return f"{base}/rds/home?region={region}#database:id={friendly_name(resource_id)};is-cluster=true"
        if resource_type == "db":
            return f"{base}/rds/home?region={region}#database:id={friendly_name(resource_id)};is-cluster=false"
        return ""

    if service == "s3":
        return f"https://s3.console.aws.amazon.com/s3/buckets/{resource_type}?region={region}"

    if service == "apigateway" and resource_type == "restapis":
        api_id = resource_id.split("/", 1)[0]
        return f"{base}/apigateway/home?region={region}#/apis/{api_id}/resources"

    if service == "apigateway" and resource_type == "apis":
        api_id = resource_id.split("/", 1)[0]
        return f"{base}/apigateway/main/api-detail?api={api_id}&region={region}"

    if service == "sns" and resource_type:
        return f"{base}/sns/v3/home?region={region}#/topic/{enc_arn}"

    if service == "sqs" and resource_type and account:
        queue_name = friendly_name(resource_id)
        queue_url = f"https://sqs.{region}.amazonaws.com/{account}/{queue_name}"
        return f"{base}/sqs/v2/home?region={region}#/queues/{urllib.parse.quote(queue_url, safe='')}"

    if service == "cloudwatch" and resource_type == "alarm":
        return f"{base}/cloudwatch/home?region={region}#alarmsV2:alarm/{urllib.parse.quote(friendly_name(resource_id))}"

    if service == "logs" and resource_type == "log-group":
        nombre = resource_id[:-2] if resource_id.endswith(":*") else resource_id
        return f"{base}/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{urllib.parse.quote(nombre, safe='')}"

    if service == "cloudformation" and resource_type == "stack":
        return f"{base}/cloudformation/home?region={region}#/stacks/stackinfo?stackId={enc_arn}"

    if service == "glue" and resource_type == "crawler":
        return f"{base}/glue/home?region={region}#/v2/data-catalog/crawlers/view/{friendly_name(resource_id)}"

    if service == "sagemaker" and resource_type == "notebook-instance":
        return f"{base}/sagemaker/home?region={region}#/notebook-instances/{friendly_name(resource_id)}"

    if service == "transfer" and resource_type == "server":
        return f"{base}/transfer/home?region={region}#/servers/{friendly_name(resource_id)}/details"

    if service == "cloudtrail" and resource_type == "trail":
        return f"{base}/cloudtrail/home?region={region}#/trails/{enc_arn}"

    if service == "access-analyzer" and resource_type == "analyzer":
        return f"{base}/access-analyzer/home?region={region}#/analyzer/{friendly_name(resource_id)}"

    if service == "elasticloadbalancing":
        return f"{base}/ec2/home?region={region}#LoadBalancer:loadBalancerArn={enc_arn}"

    if service == "ssm" and resource_type == "parameter":
        path = resource_id if resource_id.startswith("/") else "/" + resource_id
        return f"{base}/systems-manager/parameters{path}/description?region={region}"

    if service == "iam" and resource_type in ("role", "user"):
        seccion = "roles" if resource_type == "role" else "users"
        return f"https://console.aws.amazon.com/iam/home#/{seccion}/details/{friendly_name(resource_id)}"

    if service == "cloudfront" and resource_type == "distribution":
        return f"https://console.aws.amazon.com/cloudfront/v4/home#/distributions/{resource_id}"

    if service == "route53" and resource_type == "hostedzone":
        return f"https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/{resource_id}"

    return ""
