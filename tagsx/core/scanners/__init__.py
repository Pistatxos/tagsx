"""Un escáner «de verdad» (List/Describe propio) por servicio, agrupados por categoría.

`get_resources()` de la Tagging API SOLO devuelve recursos que tienen o han tenido alguna
etiqueta ("Returns all the tagged or previously tagged resources"). Para ver también lo
nunca etiquetado hay que llamar a la API de cada servicio: eso es lo que hacen estos.

Firma de cada escáner: scan(sesion, region, account, seen_arns) -> items
{"ResourceARN", "Tags": [], "Region"?}. Para añadir un servicio: escribe la función en
el módulo de su categoría y dala de alta en su SCANNERS; aquí se agrega sola.
"""
from . import (
    analytics,
    compute,
    database,
    devops,
    management,
    messaging,
    networking,
    observability,
    security,
    storage,
)

SCANNERS = {}
SCANNERS_GLOBALES_EXTRA = {}
for _module in (compute, storage, database, security, messaging, devops, observability,
                networking, analytics, management):
    SCANNERS.update(getattr(_module, "SCANNERS", {}))
    SCANNERS_GLOBALES_EXTRA.update(getattr(_module, "SCANNERS_GLOBALES_EXTRA", {}))

SERVICIOS_DETECTABLES = list(SCANNERS)

# Servicios cuyos recursos no dependen de la región: se escanean una sola vez, en us-east-1
# (S3 se lista una vez y cada bucket guarda su región).
SERVICIOS_GLOBALES = ["s3", "iam", "route53", "cloudfront", "organizations"]

# Servicios conocidos sin escáner todavía: solo se ven si ya tienen alguna etiqueta.
SERVICIOS_NO_DETECTABLES = [
    "waf",         # WAF clásico, sustituido por wafv2
    "config",      # recursos poco significativos para etiquetar (reglas/recorders)
    "inspector2",
]
