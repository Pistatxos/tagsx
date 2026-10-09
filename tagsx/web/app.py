"""El servidor web local de tagsx.

Seguridad: escucha solo en 127.0.0.1; la URL de arranque lleva un token aleatorio que se
guarda en una cookie de sesión (sin ella, 403); lo que cambia algo exige además que el
Origin sea el propio servidor; y todas las respuestas van con Cache-Control: no-store.
"""
import hmac
import io
import logging
import os
import re
import secrets
import threading
import webbrowser
from datetime import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, redirect, render_template, request, send_file

from .. import __version__
from ..core import almacen, aws, config as core_config, existencia
from ..core.aplicar import aplicar
from ..core.arn import normalizar_arn
from ..core.ficheros import escribir_csv, escribir_xlsx, leer_subido
from ..core.inventario import INFO_COLUMNS, escanear, filas_inventario
from ..core.plan import cambios_desde_filas, operaciones, planificar, resumen
from ..core.scanners import SERVICIOS_DETECTABLES, SERVICIOS_GLOBALES, SERVICIOS_NO_DETECTABLES

PUERTO_DEFECTO = 8766
HOSTS_LOCALES = ("127.0.0.1", "localhost")
REGIONES = [
    "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-central-2",
    "eu-south-1", "eu-north-1", "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "sa-east-1", "ap-south-1", "ap-northeast-1", "ap-northeast-2",
    "ap-southeast-1", "ap-southeast-2", "me-central-1", "af-south-1",
]
MAX_ITEMS = 5000


class ErrorWeb(Exception):
    def __init__(self, mensaje, status=400, **extra):
        super().__init__(mensaje)
        self.mensaje, self.status, self.extra = mensaje, status, extra


def _sesion_boto3(perfil):
    return aws.sesion(perfil)


def _codigo(e):
    return e.response.get("Error", {}).get("Code", "")


def crear_app(config_path=None, data_dir=None, token=None, sesion_factory=None, perfiles_aws=None):
    """`sesion_factory(perfil)` devuelve algo con .client(); se inyecta en los tests."""
    app = Flask(__name__)
    app.json.sort_keys = False
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    config_path = config_path or core_config.CONFIG_PATH
    data_dir = data_dir or core_config.DATA_DIR
    token = token or secrets.token_urlsafe(32)
    sesion_factory = sesion_factory or _sesion_boto3
    app.config["TX_TOKEN"] = token

    sesiones, cuentas, cerrojo = {}, {}, threading.Lock()
    lectura = {"activa": False, "mensajes": [], "error": "", "fin": None}

    def sesion(perfil):
        with cerrojo:
            if perfil not in sesiones:
                sesiones[perfil] = sesion_factory(perfil)
            return sesiones[perfil]

    def cuenta(perfil, forzar=False):
        if forzar or perfil not in cuentas:
            ident = sesion(perfil).client("sts", region_name="us-east-1").get_caller_identity()
            cuentas[perfil] = {"account": ident["Account"], "arn": ident["Arn"]}
        return cuentas[perfil]

    # ------------------------------------------------------------ config

    def leer_config():
        """(config, existe, error). Si no hay fichero, la plantilla; nunca se ejecuta."""
        existe = os.path.exists(config_path)
        try:
            return core_config.cargar(config_path), existe, ""
        except (ValueError, OSError) as e:
            return None, existe, str(e)

    def config_activa():
        config, _, error = leer_config()
        if config is None:
            raise ErrorWeb(f"No se puede leer {config_path}: {error}")
        return config

    casa = os.path.expanduser("~")
    corto = "~" + config_path[len(casa):] if config_path.startswith(casa + os.sep) else config_path

    def estado():
        config, existe, error = leer_config()
        errores, avisos = core_config.validar(config) if config else ([], [])
        datos = almacen.leer_snapshot(data_dir)
        return {
            "version": __version__, "config_path_corto": corto, "existe": existe,
            "error_lectura": error, "config": config, "errores": errores, "avisos": avisos,
            "detectables": SERVICIOS_DETECTABLES, "globales": SERVICIOS_GLOBALES,
            "no_detectables": SERVICIOS_NO_DETECTABLES, "regiones": REGIONES,
            "snapshot": None if not datos else {
                "fecha": datos.get("fecha"), "cuenta": datos.get("cuenta"),
                "perfil": datos.get("perfil", ""), "regiones": datos.get("regiones", []),
                "recursos": len(datos.get("recursos", [])),
            },
        }

    def config_de_formulario(datos):
        if not isinstance(datos, dict):
            raise ErrorWeb("Config no válida.")

        def lista_str(v):
            return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

        catalogos = {}
        for clave, valores in (datos.get("catalogos") or {}).items():
            valores = lista_str(valores)
            if str(clave).strip() and valores:
                catalogos[str(clave).strip()] = valores
        return {
            "perfil_aws": str(datos.get("perfil_aws") or "").strip(),
            "regiones": lista_str(datos.get("regiones")),
            "servicios": [s for s in lista_str(datos.get("servicios")) if s in SERVICIOS_DETECTABLES],
            "esquema": lista_str(datos.get("esquema")),
            "catalogos": catalogos,
            "minusculas": bool(datos.get("minusculas", True)),
        }

    # ------------------------------------------------------------ seguridad

    def nombre_cookie():
        return "tagsx_" + re.sub(r"\W", "_", request.host)

    @app.before_request
    def proteger():
        if request.host.rsplit(":", 1)[0] not in HOSTS_LOCALES:
            return "Host no permitido.", 403
        dado = request.args.get("token")
        if request.path == "/" and dado:
            if not hmac.compare_digest(dado, token):
                return "Token no válido: abre la URL que sale en la terminal.", 403
            resp = redirect("/")
            resp.set_cookie(nombre_cookie(), token, httponly=True, samesite="Strict", path="/")
            return resp
        if not hmac.compare_digest(request.cookies.get(nombre_cookie(), ""), token):
            return "Abre la URL que sale en la terminal al arrancar tagsx (lleva el token).", 403
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("Origin") != f"http://{request.host}":
                return jsonify({"error": "Origen no permitido."}), 403

    @app.after_request
    def cabeceras(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        return resp

    @app.errorhandler(ErrorWeb)
    def error_web(e):
        return jsonify({"error": e.mensaje, **e.extra}), e.status

    @app.errorhandler(ClientError)
    def error_cliente(e):
        if _codigo(e) in ("ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException",
                          "InvalidClientTokenId"):
            return jsonify({"error": f"Credenciales de AWS caducadas o no válidas ({_codigo(e)}). "
                                     "Si usas SSO: aws sso login --profile <perfil>."}), 400
        if _codigo(e) in ("AccessDenied", "AccessDeniedException"):
            return jsonify({"error": f"Permiso denegado: {e.response['Error'].get('Message', '')}"}), 400
        return jsonify({"error": f"AWS: {e}"}), 400

    @app.errorhandler(BotoCoreError)
    def error_botocore(e):
        return jsonify({"error": f"AWS: {e}"}), 400

    @app.errorhandler(413)
    def demasiado_grande(_e):
        return jsonify({"error": "El fichero es demasiado grande."}), 413

    def cuerpo():
        datos = request.get_json(silent=True)
        if not isinstance(datos, dict):
            raise ErrorWeb("Petición no válida.")
        return datos

    def items_de(datos):
        """Los cambios que manda la página, con los tipos comprobados:
        [{arn, cambios: {clave: valor|None}, base: {clave: valor|None}}]."""
        items = datos.get("items")
        if not isinstance(items, list) or not items:
            raise ErrorWeb("No hay cambios que revisar.")
        if len(items) > MAX_ITEMS:
            raise ErrorWeb(f"Demasiados recursos de una vez (máximo {MAX_ITEMS}).")

        def valores(d):
            if not isinstance(d, dict):
                return {}
            return {str(k): (None if v is None else str(v)) for k, v in d.items()}

        limpios = []
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("arn"), str):
                continue
            cambios = valores(it.get("cambios"))
            if cambios:
                limpios.append({"arn": normalizar_arn(it["arn"]), "cambios": cambios,
                                "base": valores(it.get("base"))})
        if not limpios:
            raise ErrorWeb("No hay cambios que revisar.")
        return limpios

    def preparar_plan(items, config):
        perfil = config["perfil_aws"]
        ses = sesion(perfil)
        datos = almacen.leer_snapshot(data_dir) or {"recursos": []}
        por_arn = {r["arn"]: r for r in datos["recursos"]}
        conocidas = {arn: r.get("region") for arn, r in por_arn.items() if r.get("region")}
        arns = [it["arn"] for it in items]
        regiones = aws.resolver_regiones(ses, arns, conocidas)
        por_region = {}
        for arn, region in regiones.items():
            if region:
                por_region.setdefault(region, []).append(arn)
        # Se relee AWS ahora mismo: lo que se compara es lo que hay, no lo que se leyó
        actuales = aws.etiquetas_actuales(ses, por_region)
        omitidos = existencia.omitidos(ses, arns, actuales, regiones, aviso=lambda _m: None)
        for it in items:
            it["nombre"] = por_arn.get(it["arn"], {}).get("nombre", "")
        return ses, planificar(items, actuales, config, regiones, omitidos)

    # ------------------------------------------------------------ páginas

    @app.get("/")
    def inicio():
        return render_template("index.html", version=__version__)

    @app.get("/api/estado")
    def api_estado():
        return jsonify(estado())

    @app.get("/api/aws/perfiles")
    def api_perfiles():
        try:
            disponibles = perfiles_aws if perfiles_aws is not None else boto3.Session().available_profiles
        except BotoCoreError:
            disponibles = []
        return jsonify({"perfiles": sorted(disponibles), "regiones": REGIONES})

    @app.post("/api/aws/probar")
    def api_probar():
        perfil = str(cuerpo().get("perfil_aws") or "")
        with cerrojo:
            sesiones.pop(perfil, None)
        return jsonify(cuenta(perfil, forzar=True))

    @app.get("/api/cuenta")
    def api_cuenta():
        perfil = config_activa()["perfil_aws"]
        return jsonify({"perfil_aws": perfil, **cuenta(perfil)})

    @app.put("/api/config")
    def api_config_guardar():
        config = config_de_formulario(cuerpo().get("config"))
        errores, avisos = core_config.validar(config)
        if errores:
            raise ErrorWeb("La configuración tiene errores.", errores=errores, avisos=avisos)
        _, _, error = leer_config()
        if error:
            raise ErrorWeb(f"No se sobrescribe {config_path}: {error}")
        core_config.guardar(config, config_path)
        return jsonify(estado())

    # ------------------------------------------------------------ inventario

    @app.get("/api/inventario")
    def api_inventario():
        return jsonify({"datos": almacen.leer_snapshot(data_dir)})

    @app.post("/api/leer")
    def api_leer():
        config = config_activa()
        errores, _ = core_config.validar(config)
        if errores:
            raise ErrorWeb("Revisa los Ajustes antes de leer.", errores=errores)
        servicios = SERVICIOS_DETECTABLES if cuerpo().get("todos") else config["servicios"]
        with cerrojo:
            if lectura["activa"]:
                raise ErrorWeb("Ya hay una lectura en marcha.")
            lectura.update(activa=True, mensajes=[], error="", fin=None)

        def leer():
            try:
                datos = escanear(sesion(config["perfil_aws"]), config["regiones"], servicios,
                                 aviso=lambda m: lectura["mensajes"].append(m.strip()))
                datos["perfil"] = config["perfil_aws"]
                almacen.guardar_snapshot(datos, data_dir)
                lectura["mensajes"].append(f"{len(datos['recursos'])} recursos.")
            except ClientError as e:
                lectura["error"] = f"AWS ({_codigo(e)}): {e.response['Error'].get('Message', '')}"
            except Exception as e:  # el hilo no puede dejar la lectura «activa» para siempre
                lectura["error"] = str(e)
            finally:
                lectura.update(activa=False, fin=datetime.now().isoformat(timespec="seconds"))

        threading.Thread(target=leer, daemon=True).start()
        return jsonify({"activa": True})

    @app.get("/api/leer")
    def api_leer_estado():
        return jsonify(lectura)

    @app.get("/api/exportar")
    def api_exportar():
        datos = almacen.leer_snapshot(data_dir)
        if not datos:
            raise ErrorWeb("Todavía no hay inventario: lee de AWS primero.")
        fieldnames, filas = filas_inventario(datos, config_activa()["esquema"])
        fecha = (datos.get("fecha") or "").replace(":", "").replace("-", "").replace("T", "_")
        if request.args.get("formato") == "csv":
            texto = io.StringIO()
            escribir_csv(texto, fieldnames, filas)
            return send_file(io.BytesIO(texto.getvalue().encode("utf-8-sig")), mimetype="text/csv",
                             as_attachment=True, download_name=f"aws_inventory_{fecha}.csv")
        salida = io.BytesIO()
        escribir_xlsx(salida, fieldnames, filas, INFO_COLUMNS)
        salida.seek(0)
        return send_file(salida, as_attachment=True, download_name=f"aws_inventory_{fecha}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/importar")
    def api_importar():
        fichero = request.files.get("fichero")
        if not fichero or not fichero.filename:
            raise ErrorWeb("Elige un fichero .xlsx o .csv.")
        if not fichero.filename.lower().endswith((".xlsx", ".csv")):
            raise ErrorWeb("Solo .xlsx o .csv.")
        datos = almacen.leer_snapshot(data_dir)
        if not datos:
            raise ErrorWeb("Lee de AWS primero: se importa comparando con el inventario.")
        try:
            fieldnames, filas = leer_subido(fichero.filename, fichero.read())
        except Exception as e:
            raise ErrorWeb(f"No se puede leer el fichero: {e}")
        if "arn" not in fieldnames:
            raise ErrorWeb("El fichero no tiene la columna 'arn'.")
        cambios, avisos = cambios_desde_filas(fieldnames, filas, {r["arn"]: r for r in datos["recursos"]},
                                              config_activa())
        return jsonify({"cambios": cambios, "avisos": avisos, "filas": len(filas)})

    # ------------------------------------------------------------ revisar y aplicar

    @app.post("/api/plan")
    def api_plan():
        config = config_activa()
        _, plan = preparar_plan(items_de(cuerpo()), config)
        perfil = config["perfil_aws"]
        return jsonify({"plan": plan, "resumen": resumen(plan), **cuenta(perfil), "perfil_aws": perfil})

    @app.post("/api/aplicar")
    def api_aplicar():
        datos = cuerpo()
        config = config_activa()
        perfil = config["perfil_aws"]
        account = cuenta(perfil)["account"]
        if str(datos.get("confirmacion") or "").strip() != f"APLICAR EN {account}":
            raise ErrorWeb(f"Para aplicar escribe exactamente: APLICAR EN {account}")
        deshace = datos.get("deshace")
        if deshace is not None and not almacen.lote(str(deshace), data_dir):
            raise ErrorWeb("El lote que se quiere deshacer no existe.")
        # El plan se vuelve a calcular aquí: lo que haya cambiado desde «Revisar» sale
        # como conflicto y no se pisa.
        ses, plan = preparar_plan(items_de(datos), config)
        ops = operaciones(plan)
        if not ops:
            raise ErrorWeb("No queda nada que aplicar (revisa conflictos y errores).", plan=plan)
        resultados = aplicar(ses, ops)
        lote = almacen.registrar_lote(resultados, account, perfil, "web",
                                      str(deshace) if deshace else None, data_dir)
        almacen.actualizar_snapshot(resultados, data_dir)
        return jsonify({"resultados": resultados, "plan": plan, "lote": lote["id"] if lote else None})

    @app.get("/api/historial")
    def api_historial():
        return jsonify({"lotes": almacen.lotes(data_dir)})

    @app.get("/api/historial/<id_lote>/deshacer")
    def api_deshacer(id_lote):
        lote = almacen.lote(id_lote, data_dir)
        if not lote:
            raise ErrorWeb("Ese lote no existe.", status=404)
        if not lote["cambios"]:
            raise ErrorWeb("Ese lote no aplicó nada: no hay qué deshacer.")
        return jsonify({"items": almacen.items_deshacer(lote), "lote": lote})

    return app


def arrancar(puerto=PUERTO_DEFECTO, abrir_navegador=True, config_path=None):
    """Arranca el servidor en 127.0.0.1 en el primer puerto libre desde `puerto` y abre el
    navegador. Ctrl+C para cerrar."""
    from werkzeug.serving import make_server

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app = crear_app(config_path=config_path)
    servidor = None
    for p in range(puerto, puerto + 50):
        try:
            servidor = make_server("127.0.0.1", p, app, threaded=True)
            break
        except OSError:
            continue
    if servidor is None:
        print(f"No hay ningún puerto libre entre {puerto} y {puerto + 49}.")
        return

    url = f"http://127.0.0.1:{servidor.server_port}/?token={app.config['TX_TOKEN']}"
    print(f"TagsX web {__version__} en {url}", flush=True)
    print("Solo escucha en este equipo. Ctrl+C para cerrar.", flush=True)
    if abrir_navegador:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nTagsX web cerrado.")
    finally:
        servidor.server_close()
