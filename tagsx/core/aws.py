"""Llamadas a la Tagging API (resourcegroupstaggingapi): leer, por región y en lotes."""
import boto3

from .arn import REGION_GLOBAL, normalizar_arn, parse_arn, region_de
from .reglas import etiquetas_visibles

# tag_resources, untag_resources y get_resources(ResourceARNList) admiten 20 ARN por llamada
LOTE = 20


def sesion(perfil="", region=None):
    return boto3.Session(profile_name=perfil or None, region_name=region or None)


def cliente_tagging(ses, region):
    return ses.client("resourcegroupstaggingapi", region_name=region)


def cuenta(ses):
    return ses.client("sts", region_name=REGION_GLOBAL).get_caller_identity()["Account"]


def get_all_resources(client, filtros=None):
    paginator = client.get_paginator("get_resources")
    kwargs = {"ResourcesPerPage": 100}
    if filtros:
        kwargs["ResourceTypeFilters"] = list(filtros)
    for page in paginator.paginate(**kwargs):
        for item in page.get("ResourceTagMappingList", []):
            yield item


def get_resources_by_arns(client, arns):
    for i in range(0, len(arns), LOTE):
        chunk = arns[i:i + LOTE]
        response = client.get_resources(ResourceARNList=chunk)
        for item in response.get("ResourceTagMappingList", []):
            yield item


def trozos(lista, n=LOTE):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def resolver_regiones(ses, arns, conocidas=None):
    """{arn: región} para operar con cada ARN. La del ARN si la lleva, us-east-1 para lo
    global y, para S3, la que ya se conozca (inventario) o la que diga el bucket. Nunca
    cae a la región por defecto: un ARN sin región que no se sabe resolver se queda en
    None y se marca como error."""
    conocidas = conocidas or {}
    regiones = {}
    s3 = None
    for arn in arns:
        region = region_de(arn) or conocidas.get(arn)
        if not region and parse_arn(arn)[0] == "s3":
            from .scanners.storage import region_bucket
            try:
                s3 = s3 or ses.client("s3", region_name=REGION_GLOBAL)
                region = region_bucket(s3, parse_arn(arn)[1])
            except Exception:
                region = None
        regiones[arn] = region
    return regiones


def etiquetas_actuales(ses, arns_por_region):
    """{arn: {clave: valor}} leído ahora mismo de AWS. Un ARN que no aparece es que nunca
    ha tenido etiquetas... o que ya no existe (la Tagging API no distingue)."""
    actuales = {}
    for region, arns in arns_por_region.items():
        client = cliente_tagging(ses, region)
        for item in get_resources_by_arns(client, list(arns)):
            actuales[normalizar_arn(item["ResourceARN"])] = etiquetas_visibles(item.get("Tags"))
    return actuales
