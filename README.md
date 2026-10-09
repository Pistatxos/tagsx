# TagsX

TagsX es una herramienta de terminal **y web** para **inventariar y corregir las etiquetas (tags) de una cuenta de AWS**.

Lee todos los recursos (también los que nunca se han etiquetado), te enseña qué falta, te deja editarlo en una tabla o en Excel y, antes de tocar nada, compara con lo que hay en AWS en ese momento.

- **Inventario completo**: la Tagging API más un escáner propio por servicio (42 servicios) para ver también lo nunca etiquetado.
- **Lo global bien leído**: IAM, CloudFront, Route 53 y WAF de CloudFront se leen y se etiquetan en `us-east-1`; cada bucket de S3, en su región.
- **Revisar antes de aplicar**: plan por recurso (crear / cambiar / borrar), con avisos y conflictos si alguien cambió algo entretanto.
- **Aplicar en lotes** de 20 ARN agrupados por cambio, comprobando `FailedResourcesMap` (AWS puede responder 200 sin aplicar).
- **Historial y deshacer** de cada lote aplicado.
- **Esquema y catálogos configurables**: tus etiquetas obligatorias y sus valores conocidos.

---

## Instalación

```bash
pip install tagsx
```

Y ejecútalo:

```bash
tagsx
```

Al arrancar pregunta **1. Web** o **2. Terminal** (o directo: `tagsx --web` / `tagsx --tui`):

- **Web**: para trabajar directamente — leer, filtrar, editar en la tabla y aplicar.
- **Terminal**: para sacar el inventario a un `.xlsx`, editarlo en Excel y cargarlo.

Las dos comparten la configuración (`~/.xsoft/tagsx_config.py`), la última lectura y el historial.

---

## Versión web

```bash
tagsx --web
```

Abre el navegador en `http://127.0.0.1:8766/?token=…` (si el puerto está ocupado, el siguiente libre). Ctrl+C para cerrar. No hace falta `tagsx configure`: se configura en **Ajustes**.

![Etiquetas](https://raw.githubusercontent.com/Pistatxos/tagsx/main/docs/img/web-etiquetas.png)

| Pantalla | Qué hace |
|---|---|
| **Etiquetas** | **Leer de AWS** (regiones de Ajustes + lo global). Arriba, la **cobertura** de cada etiqueta del esquema (% y cuántos recursos no la tienen): pulsa una tarjeta para ver solo esos. Filtros por texto, servicio y entorno, y debajo «Solo con avisos», «Solo con cambios» y «Ver las demás etiquetas»; los que estén puestos se ven siempre en la franja de filtros activos. La tabla se edita como una hoja de cálculo. |
| **Revisar** | El servidor **relee AWS en ese momento** y enseña por recurso qué se crea, cambia o borra. Si una etiqueta cambió desde que la leíste, es un **conflicto** y no se pisa. Para aplicar hay que escribir `APLICAR EN <cuenta>`. |
| **Historial** | Cada «Aplicar» es un lote con el antes y el después de cada etiqueta tocada. **Deshacer este lote** pasa por el mismo camino: revisar (con conflictos) y aplicar. |
| **Ajustes** | Perfil de AWS, regiones, servicios con escáner, esquema de etiquetas y catálogos de valores. |

![Revisar](https://raw.githubusercontent.com/Pistatxos/tagsx/main/docs/img/web-revisar.png)

En la tabla:

- Celda cambiada en **ámbar**; **vaciar una celda = borrar** esa etiqueta (en rojo); **aviso en amarillo** si un valor lleva mayúsculas (salvo `Name`) o no está en el catálogo. Los avisos no bloquean.
- **Intro** o **↓** bajan a la misma columna de la fila siguiente. Las celdas sugieren los valores del catálogo y los más usados.
- **En bloque** sobre lo seleccionado: *Poner valor*, *Quitar etiqueta*, *Pasar a minúsculas*. La casilla de la cabecera selecciona **todo lo filtrado**, no solo la página. **+ columna** añade una etiqueta nueva.
- Los cambios sin aplicar se guardan en el navegador: si cierras la pestaña, siguen ahí.

![Edición en bloque](https://raw.githubusercontent.com/Pistatxos/tagsx/main/docs/img/web-bloque.png)

- **Exportar XLSX/CSV** e **Importar…** siguen disponibles: lo importado queda como cambios pendientes en la tabla (mismas reglas que en la terminal, ver abajo) y se revisa igual.

![Historial](https://raw.githubusercontent.com/Pistatxos/tagsx/main/docs/img/web-historial.png)

Seguridad: **solo escucha en 127.0.0.1**, exige el token de la URL de arranque (en una cookie), comprueba el `Origin` en todo lo que cambia algo y responde con `Cache-Control: no-store` y una CSP estricta. La configuración se lee **como datos**, sin ejecutarla.

---

## Versión de terminal

```text
› 1. Inventario                                  genera el .xlsx y el .csv para editar en Excel
  2. Cargar aws_inventory.xlsx/.csv y aplicar    plan, confirmación y aplicar
  3. Detectar servicios activos                  sugiere los predeterminados
```

Te mueves con **↑/↓**, eliges con **Intro** o el número y sales con **Esc**. Al terminar cada opción, Intro te devuelve al menú.

1. **Inventario**: eliges *Predeterminados* (los de Ajustes) o *Todos* los servicios con escáner, y genera `exports/aws_inventory_<fecha>.xlsx` y `.csv`. Solo lectura.
2. **Cargar y aplicar**: lee `aws_inventory.xlsx` (o `.csv`) del directorio desde donde lo lanzas, enseña el plan agrupado y en color (errores, avisos, crear, actualizar, borrar), lo guarda en `exports/tagsx_plan_<fecha>.csv` y aplica tras escribir `APLICAR`. El resultado va a `exports/tagsx_applied_<fecha>.csv` y al historial (se puede deshacer desde la web).
3. **Detectar servicios activos**: tras un inventario con «Todos», propone qué servicios dejar como predeterminados y, si quieres, lo guarda.

### Reglas del fichero

| Columna | Vacía | Con valor |
|---|---|---|
| `nombre`, `id`, `servicio`, `region`, `arn`, `url` | — | Informativas: nunca se tocan |
| Las del esquema (`Name`, `Application`…) | No se toca esa etiqueta | Crea o actualiza (en minúscula, salvo `Name`, si `minusculas = True`) |
| Cualquier otra columna | **Borra** esa etiqueta si existe | Crea o actualiza tal cual |

`none` escrito en una celda **no es lo mismo que vacío**: significa «revisado, sin valor» y sí se aplica. Las columnas que empiezan por `aws:` o `kubernetes.io/` se ignoran con un aviso.

Edita y guarda en **`.xlsx`**: al exportar un `.csv` desde Excel en español, el separador pasa a `;` (se detecta solo) y `true`/`false` se convierte en `VERDADERO`/`FALSO` (se corrige solo, pero mejor evitarlo). Si abres un `.csv` en Excel, usa **Datos → Desde texto/CSV** con origen `UTF-8` y la detección de tipos «basada en todo el conjunto de datos».

### Recursos borrados y «fantasmas» de RDS

- La Tagging API solo devuelve recursos que **tienen o han tenido** etiquetas: que un ARN no aparezca puede ser que nunca se etiquetó (lo normal) o que se borró. Para instancias, volúmenes, snapshots y security groups de EC2 se comprueba de verdad y los borrados se omiten.
- Su índice puede seguir devolviendo un clúster o instancia de **RDS que ya no existe** (reemplazado o renombrado; ver [aws-cli#8197](https://github.com/aws/aws-cli/issues/8197)). Se comprueba contra la API real de RDS y esos ARN se omiten con un aviso.
- Si aun así AWS rechaza algo, sale como **error** (nunca como aplicado) con el motivo real.

---

## Configuración

`tagsx configure` crea `~/.xsoft/tagsx_config.py` con cada opción comentada (o hazlo desde **Ajustes** en la web, que conserva tus comentarios y deja el anterior como `.bak`):

```python
perfil_aws = ""                      # "" = perfil por defecto o AWS_PROFILE
regiones = ["eu-south-2"]            # lo global se lee siempre en us-east-1
servicios = ["ec2", "lambda", "rds", "s3", ...]   # los «predeterminados»
esquema = ["Name", "Application", "Environment", "Owner", "Project", "Service", "ManagedBy"]
catalogos = {
    "Environment": ["dev", "stg", "prod"],
    "ManagedBy": ["terraform", "cloudformation", "cdk", "serverless", "ansible", "manual"],
}
minusculas = True                    # valores del esquema en minúscula (salvo Name)
```

En la terminal, `AWS_REGIONS=eu-west-1,eu-south-2` manda sobre `regiones` y `OUT_DIR` cambia la carpeta de exportación.

La última lectura (`snapshot.json`) y el historial (`historial.jsonl`) se guardan en `~/.xsoft/tagsx/`, solo legibles por tu usuario.

---

## Permisos de IAM

Para leer y etiquetar:

```text
tag:GetResources, tag:TagResources, tag:UntagResources, sts:GetCallerIdentity
```

La Tagging API además necesita el permiso de etiquetar **de cada servicio** que toques, por ejemplo `ec2:CreateTags`, `ec2:DeleteTags`, `lambda:TagResource`, `lambda:UntagResource`, `rds:AddTagsToResource`, `rds:RemoveTagsFromResource`, `s3:GetBucketTagging`, `s3:PutBucketTagging`, `iam:TagRole`, `iam:UntagRole`…

Una política mínima para EC2, Lambda y S3 (añade las acciones de etiquetado de los servicios que uses):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "tag:GetResources", "tag:TagResources", "tag:UntagResources", "sts:GetCallerIdentity",
        "ec2:Describe*", "ec2:CreateTags", "ec2:DeleteTags",
        "lambda:ListFunctions", "lambda:TagResource", "lambda:UntagResource",
        "s3:ListAllMyBuckets", "s3:GetBucketLocation", "s3:GetBucketTagging", "s3:PutBucketTagging"
      ],
      "Resource": "*"
    }
  ]
}
```

Si solo vas a leer, quita `tag:TagResources`, `tag:UntagResources` y las acciones de etiquetar.

Los escáneres usan las lecturas de cada servicio (`ec2:Describe*`, `lambda:ListFunctions`, `rds:DescribeDBInstances`, `rds:DescribeDBClusters`, `s3:ListAllMyBuckets`, `s3:GetBucketLocation`, `iam:ListRoles`, `kms:ListKeys`, `kms:DescribeKey`…). Lo que tu rol no pueda leer sale como aviso y el resto se lee igual.

---

## Desarrollo

```bash
uv sync
uv run pytest                    # AWS simulada, validada contra el modelo de botocore
uv run python tests/demo_web.py --abrir   # la web con ~120 recursos simulados
uv run python -m tagsx --tui
```

Los scripts de la migración inicial están en [`scripts/`](scripts/README.md) como referencia.

Licencia MIT · [@pistatxos](https://github.com/Pistatxos)
