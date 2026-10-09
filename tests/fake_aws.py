"""AWS simulada para los tests y la demo. Cada llamada a la Tagging API se valida contra el
modelo real de botocore (nombres de campos, obligatorios, tipos), así que una petición mal
formada falla aquí igual que fallaría en AWS. Se comporta como AWS en lo que importa:

- get_resources solo devuelve lo que tiene o ha tenido etiquetas, y solo de su región.
- Lo global (IAM, CloudFront, Route 53) vive en us-east-1: desde otra región no se ve y
  etiquetarlo falla.
- tag/untag admiten 20 ARN por llamada y devuelven 200 con FailedResourcesMap si algo falla.
"""
import botocore.session
from botocore.exceptions import ClientError
from botocore.validate import validate_parameters

MODELO = botocore.session.get_session().get_service_model("resourcegroupstaggingapi")
CUENTA = "123456789012"


def error(codigo, mensaje="", op="Op"):
    return ClientError({"Error": {"Code": codigo, "Message": mensaje or codigo}}, op)


class Paginador:
    def __init__(self, metodo, token_in, token_out):
        self.metodo, self.token_in, self.token_out = metodo, token_in, token_out

    def paginate(self, **kw):
        token = None
        while True:
            pagina = self.metodo(**kw, **({self.token_in: token} if token else {}))
            yield pagina
            token = pagina.get(self.token_out)
            if not token:
                return


class Nube:
    def __init__(self, cuenta=CUENTA):
        self.cuenta = cuenta
        self.recursos = {}   # arn -> {"region", "tags", "alguna_vez"}
        self.fallan = {}     # arn -> (código, mensaje): tag/untag lo devuelven en FailedResourcesMap
        self.llamadas = []   # (servicio, región, operación, kw)
        self.buckets = {}    # nombre -> región
        self.kms = {}        # key_id -> "AWS" | "CUSTOMER"
        self.roles = []
        self.ec2 = {}        # región -> {id de instancia}
        self.rds = {}        # región -> {id de clúster}
        self.sts_falla = None

    def poner(self, arn, region, tags=None):
        self.recursos[arn] = {"region": region, "tags": dict(tags or {}), "alguna_vez": bool(tags)}
        return arn

    def tags(self, arn):
        return self.recursos[arn]["tags"]

    def ops(self, op):
        return [kw for _s, _r, o, kw in self.llamadas if o == op]

    def sesion(self, perfil=""):
        return FakeSesion(self, perfil)


class FakeSesion:
    available_profiles = ["default", "demo"]

    def __init__(self, nube, perfil=""):
        self.nube, self.perfil = nube, perfil

    def client(self, servicio, region_name=None, config=None):
        clases = {"resourcegroupstaggingapi": FakeTagging, "sts": FakeSTS, "s3": FakeS3,
                  "kms": FakeKMS, "iam": FakeIAM, "ec2": FakeEC2, "rds": FakeRDS}
        if servicio in clases:
            return clases[servicio](self.nube, region_name)
        return FakeSinPermiso(servicio)


class FakeSinPermiso:
    def __init__(self, servicio):
        self.servicio = servicio

    def __getattr__(self, nombre):
        def falla(*_a, **_k):
            raise error("AccessDeniedException", f"not authorized to perform {self.servicio}:{nombre}")
        return falla


class FakeSTS:
    def __init__(self, nube, region):
        self.nube = nube

    def get_caller_identity(self):
        if self.nube.sts_falla:
            raise error(self.nube.sts_falla, "The security token included in the request is expired")
        return {"Account": self.nube.cuenta, "Arn": f"arn:aws:iam::{self.nube.cuenta}:user/demo", "UserId": "X"}


class FakeTagging:
    def __init__(self, nube, region):
        assert region, "la Tagging API siempre se llama con región"
        self.nube, self.region = nube, region

    def _llamar(self, op, kw):
        validate_parameters(kw, MODELO.operation_model(op).input_shape)
        self.nube.llamadas.append(("tagging", self.region, op, kw))

    def get_paginator(self, nombre):
        assert nombre == "get_resources"
        return Paginador(self.get_resources, "PaginationToken", "PaginationToken")

    def get_resources(self, **kw):
        self._llamar("GetResources", kw)
        lista = kw.get("ResourceARNList")
        if lista is not None:
            assert len(lista) <= 20, "get_resources admite 20 ARN como máximo"
        filtros = kw.get("ResourceTypeFilters") or []
        arns = []
        for arn, r in sorted(self.nube.recursos.items()):
            if r["region"] != self.region or not r["alguna_vez"]:
                continue
            if lista is not None and arn not in lista:
                continue
            if filtros and not any(arn.split(":")[2] == f.split(":")[0] for f in filtros):
                continue
            arns.append(arn)
        inicio = int(kw.get("PaginationToken") or 0)
        pagina = arns[inicio:inicio + kw.get("ResourcesPerPage", 50)]
        res = {"ResourceTagMappingList": [
            {"ResourceARN": a, "Tags": [{"Key": k, "Value": v} for k, v in self.nube.recursos[a]["tags"].items()]}
            for a in pagina]}
        res["PaginationToken"] = str(inicio + len(pagina)) if inicio + len(pagina) < len(arns) else ""
        return res

    def _fallos(self, arns):
        fallos = {}
        for arn in arns:
            r = self.nube.recursos.get(arn)
            if arn in self.nube.fallan:
                codigo, mensaje = self.nube.fallan[arn]
            elif not r or r["region"] != self.region:
                codigo, mensaje = "InvalidParameterException", f"Resource {arn} not found in {self.region}"
            else:
                continue
            fallos[arn] = {"StatusCode": 400, "ErrorCode": codigo, "ErrorMessage": mensaje}
        return fallos

    def tag_resources(self, **kw):
        self._llamar("TagResources", kw)
        assert len(kw["ResourceARNList"]) <= 20, "tag_resources admite 20 ARN como máximo"
        fallos = self._fallos(kw["ResourceARNList"])
        for arn in kw["ResourceARNList"]:
            if arn not in fallos:
                r = self.nube.recursos[arn]
                r["tags"].update(kw["Tags"])
                r["alguna_vez"] = True
        return {"FailedResourcesMap": fallos}

    def untag_resources(self, **kw):
        self._llamar("UntagResources", kw)
        assert len(kw["ResourceARNList"]) <= 20, "untag_resources admite 20 ARN como máximo"
        fallos = self._fallos(kw["ResourceARNList"])
        for arn in kw["ResourceARNList"]:
            if arn not in fallos:
                for k in kw["TagKeys"]:
                    self.nube.recursos[arn]["tags"].pop(k, None)
        return {"FailedResourcesMap": fallos}


class FakeS3:
    def __init__(self, nube, region):
        self.nube = nube

    def list_buckets(self):
        return {"Buckets": [{"Name": b, "BucketRegion": r} for b, r in sorted(self.nube.buckets.items())]}

    def get_bucket_location(self, Bucket):
        region = self.nube.buckets[Bucket]
        return {"LocationConstraint": None if region == "us-east-1" else region}


class FakeKMS:
    def __init__(self, nube, region):
        self.nube, self.region = nube, region

    def get_paginator(self, nombre):
        return Paginador(lambda **kw: {"Keys": [
            {"KeyId": k, "KeyArn": f"arn:aws:kms:{self.region}:{self.nube.cuenta}:key/{k}"} for k in self.nube.kms]},
            "Marker", "NextMarker")

    def describe_key(self, KeyId):
        return {"KeyMetadata": {"KeyId": KeyId, "KeyManager": self.nube.kms[KeyId]}}


class FakeIAM:
    def __init__(self, nube, region):
        self.nube = nube

    def get_paginator(self, nombre):
        datos = {
            "list_roles": {"Roles": [{"Arn": f"arn:aws:iam::{self.nube.cuenta}:role/{r}"} for r in self.nube.roles]},
            "list_users": {"Users": []},
            "list_policies": {"Policies": []},
        }[nombre]
        return Paginador(lambda **kw: datos, "Marker", "Marker")


class FakeEC2:
    def __init__(self, nube, region):
        self.nube, self.region = nube, region

    def describe_instances(self, InstanceIds):
        faltan = [i for i in InstanceIds if i not in self.nube.ec2.get(self.region, set())]
        if faltan:
            raise error("InvalidInstanceID.NotFound", f"The instance IDs '{', '.join(faltan)}' do not exist")
        return {"Reservations": []}

    def get_paginator(self, nombre):
        return Paginador(lambda **kw: {}, "NextToken", "NextToken")


class FakeRDS:
    def __init__(self, nube, region):
        self.nube, self.region = nube, region

    def get_paginator(self, nombre):
        if nombre == "describe_db_clusters":
            datos = {"DBClusters": [{"DBClusterIdentifier": c} for c in self.nube.rds.get(self.region, set())]}
        else:
            datos = {"DBInstances": []}
        return Paginador(lambda **kw: datos, "Marker", "Marker")
