"""Aplicar en AWS: en lotes de 20 ARN que llevan el mismo cambio, por región.

tag_resources/untag_resources no siempre lanzan excepción cuando algo falla (p. ej. un
recurso ya borrado): a veces devuelven 200 OK con el ARN en FailedResourcesMap. Se revisa
siempre, para no contar como aplicado algo que AWS no aplicó.
"""
from .aws import cliente_tagging, trozos


def check_failed_resources(response, arn):
    failure = response.get("FailedResourcesMap", {}).get(arn)
    if failure:
        raise RuntimeError(f"{failure.get('ErrorCode')}: {failure.get('ErrorMessage')}")


def _fallos(response):
    return {arn: f"{f.get('ErrorCode')}: {f.get('ErrorMessage')}"
            for arn, f in (response.get("FailedResourcesMap") or {}).items()}


def aplicar(ses, ops):
    """`ops`: [{arn, region, poner: {clave: valor}, quitar: [clave], antes: {clave: valor}}].

    Devuelve un resultado por ARN: {arn, region, estado: aplicado|parcial|error, errores,
    antes, despues}, donde antes/después solo llevan las claves que AWS sí aplicó (es lo
    que va al historial y lo que se deshace)."""
    res = {op["arn"]: {"arn": op["arn"], "region": op["region"], "errores": [],
                       "antes": {}, "despues": {}, "_op": op} for op in ops}
    clientes = {}

    def cliente(region):
        if region not in clientes:
            clientes[region] = cliente_tagging(ses, region)
        return clientes[region]

    def lanzar(grupos, llamada, al_ir_bien):
        for (region, clave), arns in grupos.items():
            for lote in trozos(arns):
                try:
                    fallos = _fallos(llamada(cliente(region), lote, clave))
                except Exception as exc:
                    fallos = {arn: str(exc) for arn in lote}
                for arn in lote:
                    if arn in fallos:
                        res[arn]["errores"].append(fallos[arn])
                    else:
                        al_ir_bien(res[arn], clave)

    # Mismo cambio y misma región = una llamada para hasta 20 ARN
    poner, quitar = {}, {}
    for op in ops:
        if op["poner"]:
            poner.setdefault((op["region"], tuple(sorted(op["poner"].items()))), []).append(op["arn"])
        if op["quitar"]:
            quitar.setdefault((op["region"], tuple(sorted(op["quitar"]))), []).append(op["arn"])

    def puesto(r, clave):
        for k, v in clave:
            r["antes"][k] = r["_op"]["antes"].get(k)
            r["despues"][k] = v

    def quitado(r, clave):
        for k in clave:
            r["antes"][k] = r["_op"]["antes"].get(k)
            r["despues"][k] = None

    lanzar(poner, lambda c, lote, clave: c.tag_resources(ResourceARNList=lote, Tags=dict(clave)), puesto)
    lanzar(quitar, lambda c, lote, clave: c.untag_resources(ResourceARNList=lote, TagKeys=list(clave)), quitado)

    resultados = []
    for r in res.values():
        r.pop("_op")
        r["estado"] = "error" if r["errores"] and not r["despues"] else "parcial" if r["errores"] else "aplicado"
        resultados.append(r)
    return resultados
