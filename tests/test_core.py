"""El núcleo: ARN y regiones, inventario, plan, aplicar en lotes, historial, ficheros y config."""
import io

import openpyxl
import pytest

from conftest import R, arn_ec2
from fake_aws import CUENTA
from tagsx.core import almacen, aws, config as core_config
from tagsx.core.aplicar import aplicar, check_failed_resources
from tagsx.core.arn import build_url, classify_service, normalizar_arn, parse_arn, region_de
from tagsx.core.existencia import find_missing_ec2_ids, omitidos
from tagsx.core.ficheros import escribir_xlsx, leer_subido, read_csv_rows, read_xlsx_rows
from tagsx.core.inventario import escanear, filas_inventario
from tagsx.core.plan import build_row_plan, cambios_desde_filas, columnas_dinamicas, operaciones, planificar

IAM = f"arn:aws:iam::{CUENTA}:role/despliegue"
CF = f"arn:aws:cloudfront::{CUENTA}:distribution/E123"
ZONA = "arn:aws:route53:::hostedzone/Z1"


# --------------------------------------------------------------------------- ARN

def test_parse_arn():
    assert parse_arn(arn_ec2(1)) == ("ec2", "instance", "i-0001", R, CUENTA)
    assert parse_arn("arn:aws:s3:::mi-bucket") == ("s3", "mi-bucket", "mi-bucket", "", "")
    assert parse_arn(f"arn:aws:rds:{R}:{CUENTA}:cluster:db-1") == ("rds", "cluster", "db-1", R, CUENTA)
    assert parse_arn(f"arn:aws:apigateway:{R}::/restapis/abc") == ("apigateway", "restapis", "abc", R, "")
    assert parse_arn(f"arn:aws:sns:{R}:{CUENTA}:avisos")[1:3] == ("avisos", "avisos")


def test_lo_global_va_a_us_east_1_y_s3_no_cae_a_la_region_por_defecto():
    assert region_de(IAM) == "us-east-1"
    assert region_de(CF) == "us-east-1"
    assert region_de(ZONA) == "us-east-1"
    assert region_de(arn_ec2(1)) == R
    assert region_de("arn:aws:s3:::mi-bucket") is None


def test_normalizar_log_group_y_clasificar():
    lg = f"arn:aws:logs:{R}:{CUENTA}:log-group:/aws/lambda/x"
    assert normalizar_arn(lg + ":*") == lg
    assert normalizar_arn(lg) == lg
    assert classify_service("ec2", "subnet") == "vpc"
    assert classify_service("ec2", "instance") == "ec2"
    assert classify_service("apigateway", "apis") == "apigatewayv2"
    assert "InstanceDetails:instanceId=i-0001" in build_url("ec2", "instance", "i-0001", arn_ec2(1), R)


def test_resolver_regiones_pregunta_a_s3(nube):
    nube.buckets["datos"] = "eu-west-1"
    regiones = aws.resolver_regiones(nube.sesion(), ["arn:aws:s3:::datos", IAM, arn_ec2(1)])
    assert regiones == {"arn:aws:s3:::datos": "eu-west-1", IAM: "us-east-1", arn_ec2(1): R}


# --------------------------------------------------------------------------- inventario

def test_inventario_lee_lo_global_en_us_east_1(nube):
    nube.poner(arn_ec2(1), R, {"Name": "web", "PatchGroup": "a", "aws:cloudformation:stack-name": "x"})
    nube.poner(IAM, "us-east-1", {"Owner": "infra"})
    nube.poner(f"arn:aws:ec2:us-east-1:{CUENTA}:instance/i-9999", "us-east-1", {"Name": "otra region"})
    nube.roles = ["despliegue", "sin-etiquetas"]
    nube.buckets = {"logs": "eu-west-1"}
    nube.kms = {"k-propia": "CUSTOMER", "k-aws": "AWS"}

    datos = escanear(nube.sesion(), [R], ["s3", "iam", "kms"])
    por_arn = {r["arn"]: r for r in datos["recursos"]}

    assert por_arn[arn_ec2(1)]["tags"] == {"Name": "web", "PatchGroup": "a"}  # sin aws:
    assert por_arn[arn_ec2(1)]["nombre"] == "web"
    assert por_arn[IAM]["region"] == "us-east-1"
    assert por_arn[IAM]["tags"] == {"Owner": "infra"}
    assert por_arn[f"arn:aws:iam::{CUENTA}:role/sin-etiquetas"]["tags"] == {}
    assert por_arn["arn:aws:s3:::logs"]["region"] == "eu-west-1"
    assert f"arn:aws:kms:{R}:{CUENTA}:key/k-propia" in por_arn
    assert f"arn:aws:kms:{R}:{CUENTA}:key/k-aws" not in por_arn       # gestionada por AWS
    assert f"arn:aws:ec2:us-east-1:{CUENTA}:instance/i-9999" not in por_arn  # región no elegida
    assert datos["claves"] == ["Name", "PatchGroup", "Owner"]
    # Lo global se pide en us-east-1 con filtro, no la región entera
    globales = [kw for s, r, op, kw in nube.llamadas if op == "GetResources" and r == "us-east-1"]
    assert globales and all(kw.get("ResourceTypeFilters") for kw in globales)

    fieldnames, filas = filas_inventario(datos, ["Name", "Owner"])
    assert fieldnames == ["nombre", "id", "servicio", "region", "arn", "url", "Name", "Owner", "PatchGroup"]


# --------------------------------------------------------------------------- plan (CSV)

def test_reglas_del_csv(config):
    actuales = {"Name": "web", "Owner": "ana", "PatchGroup": "a", "Viejo": "x"}
    fila = {"arn": "a", "Name": "", "Application": "CORE", "Environment": "none",
            "Owner": "ana", "PatchGroup": "b", "Viejo": "", "Nueva": "VERDADERO"}
    plan = build_row_plan("a", fila, actuales, ["PatchGroup", "Viejo", "Nueva"], config)
    # esquema vacío no toca Name; minúsculas en el esquema; 'none' es un valor
    assert plan["apply_tags"] == {"Application": "core", "Environment": "none", "PatchGroup": "b", "Nueva": "true"}
    assert plan["remove_keys"] == ["Viejo"]  # columna ajena vacía = borrar
    assert plan["antes"]["Viejo"] == "x" and plan["antes"]["Application"] is None
    assert plan["status"] == "planned"


def test_csv_sin_cambios_y_avisos_de_catalogo(config):
    assert build_row_plan("a", {"Owner": "ana"}, {"Owner": "ana"}, [], config) is None
    plan = build_row_plan("a", {"Environment": "pre"}, {}, [], config)
    assert any("catálogo" in n for n in plan["notes_list"])


def test_limites_y_prefijos_reservados(config):
    columnas, avisos = columnas_dinamicas(["arn", "nombre", "Name", "aws:x", "kubernetes.io/y", "", "Ok"], config["esquema"])
    assert columnas == ["Ok"] and len(avisos) == 2

    largo = build_row_plan("a", {"Owner": "x" * 257}, {}, [], config)
    assert largo["status"] == "error"
    muchas = {f"k{i}": "v" for i in range(50)}
    plan = build_row_plan("a", {"Owner": "ana"}, muchas, [], config)
    assert plan["status"] == "error" and "50" in plan["errores"][0]


def test_importar_compara_con_la_instantanea(config):
    recursos = {"a": {"tags": {"Owner": "ana", "Tmp": "1"}}}
    cambios, avisos = cambios_desde_filas(["arn", "Owner", "Tmp"], [
        {"arn": "a", "Owner": "luis", "Tmp": ""}, {"arn": "desconocido", "Owner": "x", "Tmp": ""}], recursos, config)
    assert cambios == {"a": {"Owner": "luis", "Tmp": None}}
    assert "1 fila" in avisos[0]


# --------------------------------------------------------------------------- plan (web)

def test_planificar_vaciar_borra_conflicto_y_avisos(config):
    items = [
        {"arn": "a", "cambios": {"Owner": None, "Environment": "PROD", "Application": "core"},
         "base": {"Owner": "ana", "Environment": None, "Application": "data"}},
        {"arn": "b", "cambios": {"Owner": "luis"}, "base": {"Owner": None}},
    ]
    actuales = {"a": {"Owner": "ana", "Application": "otra"}, "b": {"Owner": "luis"}}
    plan = planificar(items, actuales, config, {"a": R, "b": R})
    a, b = plan
    assert a["borrar"] == {"Owner": "ana"}
    assert a["crear"] == {"Environment": "PROD"}
    assert a["conflictos"] == [{"clave": "Application", "leido": "data", "ahora": "otra", "nuevo": "core"}]
    assert any("mayúsculas" in x for x in a["avisos"]) and any("catálogo" in x for x in a["avisos"])
    assert a["estado"] == "ok"
    assert b["estado"] == "nada" and b["sin_cambio"] == ["Owner"]  # ya estaba así
    assert operaciones(plan) == [{"arn": "a", "region": R, "poner": {"Environment": "PROD"},
                                  "quitar": ["Owner"], "antes": {"Environment": None, "Owner": "ana"}}]


def test_planificar_errores_bloquean_el_recurso(config):
    plan = planificar([{"arn": "a", "cambios": {"aws:x": "1"}, "base": {}},
                       {"arn": "s3", "cambios": {"Owner": "x"}, "base": {}}], {}, config, {"a": R, "s3": None})
    assert [p["estado"] for p in plan] == ["error", "error"]
    assert operaciones(plan) == []


# --------------------------------------------------------------------------- aplicar

def test_aplicar_en_lotes_de_20_agrupados_por_cambio(nube):
    arns = [nube.poner(arn_ec2(i), R) for i in range(45)]
    otros = [nube.poner(arn_ec2(100 + i), R) for i in range(3)]
    ops = [{"arn": a, "region": R, "poner": {"Owner": "ana"}, "quitar": [], "antes": {"Owner": None}} for a in arns]
    ops += [{"arn": a, "region": R, "poner": {"Owner": "luis"}, "quitar": [], "antes": {}} for a in otros]
    resultados = aplicar(nube.sesion(), ops)

    llamadas = nube.ops("TagResources")
    assert sorted(len(kw["ResourceARNList"]) for kw in llamadas) == [3, 5, 20, 20]
    assert all(r["estado"] == "aplicado" for r in resultados)
    assert nube.tags(arns[44]) == {"Owner": "ana"}
    assert resultados[0]["antes"] == {"Owner": None} and resultados[0]["despues"] == {"Owner": "ana"}


def test_failed_resources_map_no_cuenta_como_aplicado(nube):
    bien, mal = nube.poner(arn_ec2(1), R), nube.poner(arn_ec2(2), R)
    nube.fallan[mal] = ("InvalidParameterException", "borrado")
    ops = [{"arn": a, "region": R, "poner": {"Owner": "ana"}, "quitar": ["Viejo"], "antes": {}} for a in (bien, mal)]
    res = {r["arn"]: r for r in aplicar(nube.sesion(), ops)}
    assert res[bien]["estado"] == "aplicado"
    assert res[mal]["estado"] == "error" and "borrado" in res[mal]["errores"][0]
    assert res[mal]["despues"] == {}
    with pytest.raises(RuntimeError):
        check_failed_resources({"FailedResourcesMap": {mal: {"ErrorCode": "X", "ErrorMessage": "y"}}}, mal)


def test_lo_global_se_etiqueta_en_us_east_1(nube):
    nube.poner(IAM, "us-east-1")
    ses = nube.sesion()
    regiones = aws.resolver_regiones(ses, [IAM])
    res = aplicar(ses, [{"arn": IAM, "region": regiones[IAM], "poner": {"Owner": "ana"}, "quitar": [], "antes": {}}])
    assert res[0]["estado"] == "aplicado" and nube.tags(IAM) == {"Owner": "ana"}
    # Con la región por defecto (lo que pasaba antes) AWS lo rechaza
    mal = aplicar(ses, [{"arn": IAM, "region": R, "poner": {"Owner": "x"}, "quitar": [], "antes": {}}])
    assert mal[0]["estado"] == "error"


def test_existencia_ec2_y_rds(nube):
    nube.ec2[R] = {"i-0001"}
    assert find_missing_ec2_ids(nube.sesion(), R, "instance", ["i-0001", "i-0002", "i-0003"]) == {"i-0002", "i-0003"}
    fantasma = f"arn:aws:rds:{R}:{CUENTA}:cluster:viejo"
    vivo = f"arn:aws:rds:{R}:{CUENTA}:cluster:nuevo"
    nube.rds[R] = {"nuevo"}
    motivos = omitidos(nube.sesion(), [arn_ec2(2), fantasma, vivo], {fantasma: {}, vivo: {}},
                       {arn_ec2(2): R, fantasma: R, vivo: R}, aviso=lambda _m: None)
    assert set(motivos) == {arn_ec2(2), fantasma}


# --------------------------------------------------------------------------- historial

def test_historial_y_deshacer(tmp_path):
    d = str(tmp_path)
    resultados = [{"arn": "a", "region": R, "estado": "aplicado", "errores": [],
                   "antes": {"Owner": None, "Env": "dev"}, "despues": {"Owner": "ana", "Env": None}},
                  {"arn": "b", "region": R, "estado": "error", "errores": ["x"], "antes": {}, "despues": {}}]
    lote = almacen.registrar_lote(resultados, CUENTA, data_dir=d)
    assert lote["cambios"] == [{"arn": "a", "region": R, "antes": {"Owner": None, "Env": "dev"},
                                "despues": {"Owner": "ana", "Env": None}}]
    assert lote["errores"] == [{"arn": "b", "errores": ["x"]}]
    segundo = almacen.registrar_lote(resultados, CUENTA, deshace=lote["id"], data_dir=d)
    assert [l["id"] for l in almacen.lotes(d)] == [segundo["id"], lote["id"]]
    assert almacen.items_deshacer(lote) == [{"arn": "a", "cambios": {"Owner": None, "Env": "dev"},
                                             "base": {"Owner": "ana", "Env": None}}]
    assert almacen.registrar_lote([], CUENTA, data_dir=d) is None


# --------------------------------------------------------------------------- ficheros

def test_csv_de_excel_en_espanol(tmp_path):
    p = tmp_path / "aws_inventory.csv"
    p.write_bytes("﻿arn;Owner;Notas\na;ana;uno, dos\n".encode("utf-8"))
    fieldnames, filas = read_csv_rows(str(p))
    assert fieldnames == ["arn", "Owner", "Notas"]
    assert filas == [{"arn": "a", "Owner": "ana", "Notas": "uno, dos"}]


def test_xlsx_booleanos_y_numeros(tmp_path):
    p = str(tmp_path / "x.xlsx")
    wb = openpyxl.Workbook()
    wb.active.append(["arn", "PatchEnabled", "Cost", None])
    wb.active.append(["a", True, 12.0, None])
    wb.active.append([None, None, None, None])
    wb.save(p)
    fieldnames, filas = read_xlsx_rows(p)
    assert filas == [{"arn": "a", "PatchEnabled": "true", "Cost": "12", "": ""}]


def test_xlsx_ida_y_vuelta():
    salida = io.BytesIO()
    escribir_xlsx(salida, ["arn", "Owner"], [{"arn": "a", "Owner": "0012"}], ["arn"])
    fieldnames, filas = leer_subido("x.xlsx", salida.getvalue())
    assert filas == [{"arn": "a", "Owner": "0012"}]


# --------------------------------------------------------------------------- config

def test_config_guarda_conservando_comentarios(tmp_path, config):
    path = str(tmp_path / "c.py")
    core_config.guardar(config, path)
    texto = open(path, encoding="utf-8").read()
    assert "# Perfil de ~/.aws/credentials" in texto
    assert core_config.cargar(path) == config
    core_config.guardar({**config, "regiones": ["eu-west-1"]}, path)
    assert core_config.cargar(path)["regiones"] == ["eu-west-1"]
    assert open(path + ".bak", encoding="utf-8").read() == texto


def test_config_valida(config):
    assert core_config.validar(config) == ([], [])
    errores, _ = core_config.validar({**config, "esquema": ["Owner", "Owner", "aws:x"], "regiones": []})
    assert len(errores) == 3


def test_config_no_ejecuta_el_fichero(tmp_path):
    path = tmp_path / "c.py"
    path.write_text("import os\nregiones = os.environ['X']\n")
    with pytest.raises(core_config.ConfigNoLegible):
        core_config.cargar(str(path))
