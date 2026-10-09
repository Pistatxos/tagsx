"""¿Sigue existiendo el recurso? La Tagging API no lo distingue bien:

- Un ARN que no devuelve puede ser un recurso que nunca se ha etiquetado (lo normal al
  etiquetar por primera vez) o uno ya borrado. Para los tipos de EC2 que se pueden
  comprobar se pregunta a EC2 (find_missing_resources).
- Un ARN de RDS que SÍ devuelve puede ser un «fantasma»: su índice tarda días o semanas en
  purgar un clúster/instancia reemplazado o renombrado (aws-cli#8197, boto3#3341). Se
  comprueba contra la API real de RDS (find_ghost_rds_resources).
"""
import re

from botocore.exceptions import ClientError

from .arn import parse_arn

# describe_volumes/describe_snapshots/describe_instances/describe_security_groups
# fallan enteros si algun id de la lista no existe (no hay respuesta parcial),
# nombrando el id invalido en el mensaje de error. Vamos quitando de la lista
# los ids que el error va señalando y reintentando, hasta que la llamada
# tenga exito con los que queden - así identificamos justo los que no
# existen sin tener que consultarlos uno a uno.
EC2_EXISTENCE_CHECKS = {
    "volume": ("describe_volumes", "VolumeIds"),
    "snapshot": ("describe_snapshots", "SnapshotIds"),
    "instance": ("describe_instances", "InstanceIds"),
    "security-group": ("describe_security_groups", "GroupIds"),
}

# Con varios a la vez AWS los junta en las mismas comillas: "The instance IDs 'i-1, i-2' do not exist"
_IDS_IN_ERROR_MESSAGE = re.compile(r"'([^']+)'")


def find_missing_ec2_ids(ses, region, resource_type, ids):
    method, param_name = EC2_EXISTENCE_CHECKS[resource_type]
    client = ses.client("ec2", region_name=region)
    remaining = list(dict.fromkeys(ids))
    missing = set()

    while remaining:
        try:
            getattr(client, method)(**{param_name: remaining})
            return missing
        except ClientError as exc:
            message = exc.response.get("Error", {}).get("Message", "")
            found = {i.strip() for grupo in _IDS_IN_ERROR_MESSAGE.findall(message)
                     for i in grupo.split(",") if i.strip() in remaining}
            if not found:
                # No se pudo identificar el id del mensaje de error (p.ej. un
                # problema de permisos, no de existencia): no se puede seguir
                # afinando, se deja de comprobar este lote sin dar falsos
                # positivos de "no existe".
                return missing
            missing.update(found)
            remaining = [i for i in remaining if i not in found]

    return missing


def find_missing_resources(ses, ambiguous_arns, regiones, aviso=print):
    """De los ARN que la Tagging API no devolvió, los que EC2 confirma como borrados."""
    by_region_type = {}
    for arn in ambiguous_arns:
        service, resource_type, resource_id, _, _ = parse_arn(arn)
        if service != "ec2" or resource_type not in EC2_EXISTENCE_CHECKS or not regiones.get(arn):
            continue
        by_region_type.setdefault((regiones[arn], resource_type), []).append((resource_id, arn))

    missing_arns = set()
    for (region, resource_type), pairs in by_region_type.items():
        try:
            missing_ids = find_missing_ec2_ids(ses, region, resource_type, [rid for rid, _ in pairs])
        except Exception as exc:
            aviso(f"  Aviso: no se pudo comprobar existencia de {resource_type} en {region}: {exc}")
            continue
        missing_arns.update(arn for rid, arn in pairs if rid in missing_ids)
    return missing_arns


RDS_EXISTENCE_CHECKS = {
    "cluster": ("describe_db_clusters", "DBClusters", "DBClusterIdentifier"),
    "db": ("describe_db_instances", "DBInstances", "DBInstanceIdentifier"),
}


def find_ghost_rds_resources(ses, rds_arns, regiones, aviso=print):
    by_region_type = {}
    for arn in rds_arns:
        service, resource_type, resource_id, _, _ = parse_arn(arn)
        if service != "rds" or resource_type not in RDS_EXISTENCE_CHECKS or not regiones.get(arn):
            continue
        by_region_type.setdefault((regiones[arn], resource_type), []).append((resource_id, arn))

    ghost_arns = set()
    for (region, resource_type), pairs in by_region_type.items():
        method, list_key, id_key = RDS_EXISTENCE_CHECKS[resource_type]
        client = ses.client("rds", region_name=region)
        try:
            existing_ids = set()
            for page in client.get_paginator(method).paginate():
                for item in page.get(list_key, []):
                    existing_ids.add(item[id_key])
        except Exception as exc:
            aviso(f"  Aviso: no se pudo comprobar existencia real de {resource_type} en {region}: {exc}")
            continue
        ghost_arns.update(arn for rid, arn in pairs if rid not in existing_ids)
    return ghost_arns


MOTIVO_BORRADO = "recurso no encontrado en AWS (probablemente borrado)."
MOTIVO_FANTASMA = (
    "posible fantasma en RDS: el indice de tags de AWS todavia lista este ARN "
    "(a veces ya con valores actualizados) pero ya no existe en RDS real - "
    "normalmente porque el cluster/instancia se reemplazo o se renombro. No "
    "pasa nada: no se aplica ninguna tag y el recurso real, si sigue vivo con "
    "otro ARN, no se ve afectado. Ver README, 'Recursos fantasma en RDS'."
)


def omitidos(ses, arns, actuales, regiones, aviso=print):
    """{arn: motivo} de lo que no se debe intentar etiquetar."""
    ambiguos = [a for a in arns if a not in actuales]
    motivos = {a: MOTIVO_BORRADO for a in find_missing_resources(ses, ambiguos, regiones, aviso)}
    rds = [a for a in arns if parse_arn(a)[0] == "rds"]
    motivos.update({a: MOTIVO_FANTASMA for a in find_ghost_rds_resources(ses, rds, regiones, aviso)})
    return motivos
