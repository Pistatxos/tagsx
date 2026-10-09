# Scripts de migración (ejemplo)

Los scripts con los que se hizo una **migración puntual** a un esquema de etiquetas nuevo,
antes de que existiera tagsx. No forman parte del paquete (no se instalan con pip): están
aquí como referencia por si te toca algo parecido. Para el día a día usa `tagsx`.

Los diccionarios de configuración (catálogos, mapas de Owner, listas de ARN) son
**ejemplos inventados**: cámbialos por los tuyos antes de usarlos. Todos generan un plan en
`exports/` y piden escribir `APLICAR` antes de tocar AWS.

| Script | Qué hace |
|---|---|
| `1_audit.py` | Auditoría: un CSV con una fila por etiqueta (`region,service,resource_type,arn,tag_key,tag_value`) y resúmenes por clave y por clave/valor. Solo lectura. |
| `2_cleaner.py` | Renombra claves antiguas a la estándar (`KEY_RENAMES`) y normaliza valores (`VALUE_REPLACEMENTS`). |
| `3_individual.py` | Cambios a mano sobre un ARN (o una lista). |
| `4_borrar_tags.py` | Borra etiquetas concretas (`DELETE_TAGS`) de una lista de ARN o de toda la cuenta. |
| `5_application_tags.py` | Reparte un `Application` antiguo en `Application` + `Project` + `Service` con `APPLICATION_MAP`. |
| `6_schema_migration.py` | Migración al esquema completo con `PROJECT_CATALOG`, `OWNER_MAP` y el `Service` derivado del ARN. |
| `7_service_inventory.py` | El inventario por servicio del que salió el de tagsx. |
| `8_tags_logs_lambda.sh` | Copia las etiquetas de cada Lambda a su log group `/aws/lambda/<función>` (AWS CLI; aplica directamente, sin plan). |

```bash
AWS_REGIONS=eu-south-2,eu-west-1 python3 scripts/1_audit.py
```

Usan las credenciales por defecto de boto3 (`AWS_PROFILE`) y `AWS_REGION`/`AWS_REGIONS`.
Ojo: no tienen los arreglos de tagsx (lo global en us-east-1, lotes de 20, límites).
