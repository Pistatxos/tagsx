# Changelog

## 0.1.0

Primera versión publicable, a partir de `xtags.py` (herramienta interna de terminal).

### Añadido

- **Paquete `tagsx`** con comando `tagsx`: pregunta **Web o Terminal** (o `--web` / `--tui`). `tagsx configure`, `--help`, `--version`.
- **Versión web** (se instala con el paquete, Flask incluido): Flask local en 127.0.0.1 con token y comprobación de `Origin`. Cobertura por etiqueta, filtros con franja de filtros activos, tabla tipo hoja de cálculo (vaciar = borrar, avisos de mayúsculas y catálogo), edición en bloque, «+ columna», Revisar contra AWS en vivo con conflictos, Aplicar con `APLICAR EN <cuenta>`, Historial con «Deshacer este lote», Exportar/Importar XLSX y CSV, y Ajustes.
- **Configuración** en `~/.xsoft/tagsx_config.py`, leída como datos (sin ejecutarla): perfil de AWS, regiones, servicios, esquema de etiquetas y catálogos. Antes era `config.py` junto al script y el esquema estaba fijo en el código.
- **Instantánea** de la última lectura e **historial** de lo aplicado en `~/.xsoft/tagsx/`.
- **Menú de terminal** con el estilo de paramsx: logo en color, ↑/↓ e Intro (o el número), Esc para volver o salir, firma abajo y el plan coloreado. Vuelve al menú al acabar cada opción.
- El inventario de la terminal genera también el `.xlsx`, con todo como texto para que Excel no convierta valores.
- Escáneres de **API Gateway v2** (HTTP/WebSocket) y **WAF v2** (REGIONAL por región y CLOUDFRONT en us-east-1).
- Validación de límites: ≤50 etiquetas por recurso, clave ≤128, valor ≤256; los prefijos `aws:` y `kubernetes.io/` se ignoran con aviso.

### Corregido

- **Lo global** (IAM, CloudFront, Route 53) se lee y se etiqueta en **us-east-1**: antes salía «sin tags» y fallaba al aplicar. Un ARN sin región ya no cae a `AWS_REGION`: cada bucket de S3 se opera en su región.
- `tag_resources`/`untag_resources` se llaman con **hasta 20 ARN** agrupados por cambio (antes, de uno en uno).
- KMS ya no lista las claves gestionadas por AWS (no se pueden etiquetar).
- Los log groups se etiquetan con el ARN sin el `:*` final.
- La comprobación de recursos EC2 borrados reconoce el mensaje de AWS con varios ids a la vez.

### Quitado

- La opción «Comprobar servicios sin escáner» de la terminal: solo quedan `waf` (clásico), `config` e `inspector2`, y un 0 no demostraba nada.
- Las «relaciones físicas» (sugerir etiquetas de un recurso a partir de otro), que estaban desactivadas.
