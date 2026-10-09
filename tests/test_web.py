"""La web: seguridad, leer, revisar (con conflictos), aplicar, historial y deshacer, importar y exportar."""
import io
import time

import pytest

from conftest import R, arn_ec2
from fake_aws import CUENTA
from tagsx.core import almacen
from tagsx.web.app import crear_app

TOKEN = "t" * 32
ORIGEN = {"Origin": "http://127.0.0.1"}


@pytest.fixture
def entorno(tmp_path, nube, config_path):
    app = crear_app(config_path=config_path, data_dir=str(tmp_path / "datos"), token=TOKEN,
                    sesion_factory=nube.sesion, perfiles_aws=["default"])
    cliente = app.test_client()
    cliente.get(f"/?token={TOKEN}", base_url="http://127.0.0.1")
    return cliente, nube, str(tmp_path / "datos")


def get(c, url):
    return c.get(url, base_url="http://127.0.0.1")


def post(c, url, datos=None, **kw):
    return c.post(url, json=datos, headers=ORIGEN, base_url="http://127.0.0.1", **kw)


def leer(c):
    assert post(c, "/api/leer", {}).status_code == 200
    for _ in range(100):
        estado = get(c, "/api/leer").get_json()
        if not estado["activa"]:
            return estado
        time.sleep(0.02)
    raise AssertionError("la lectura no termina")


def test_seguridad(tmp_path, nube, config_path):
    app = crear_app(config_path=config_path, data_dir=str(tmp_path), token=TOKEN, sesion_factory=nube.sesion)
    c = app.test_client()
    assert get(c, "/api/estado").status_code == 403                       # sin cookie
    assert get(c, "/?token=otro").status_code == 403                      # token malo
    assert c.get(f"/?token={TOKEN}", base_url="http://evil.com").status_code == 403  # Host ajeno
    assert get(c, f"/?token={TOKEN}").status_code == 302
    assert get(c, "/api/estado").status_code == 200
    r = c.post("/api/leer", json={}, base_url="http://127.0.0.1", headers={"Origin": "http://evil.com"})
    assert r.status_code == 403                                            # Origin ajeno
    r = get(c, "/")
    assert "no-store" in r.headers["Cache-Control"] and "default-src 'self'" in r.headers["Content-Security-Policy"]
    html = r.get_data(as_text=True)
    assert 'autocomplete="off"' in html and "email" not in html.lower()


def test_leer_revisar_aplicar_y_deshacer(entorno):
    c, nube, datos_dir = entorno
    a, b = nube.poner(arn_ec2(1), R, {"Owner": "ana", "Tmp": "1"}), nube.poner(arn_ec2(2), R, {"Owner": "luis"})
    estado = leer(c)
    assert not estado["error"]
    datos = get(c, "/api/inventario").get_json()["datos"]
    assert {r["arn"] for r in datos["recursos"]} == {a, b}

    # Alguien cambia b en AWS después de leer: conflicto, no se pisa
    nube.tags(b)["Owner"] = "marta"
    items = [{"arn": a, "cambios": {"Owner": "pepe", "Tmp": None, "Environment": "prod"},
              "base": {"Owner": "ana", "Tmp": "1", "Environment": None}},
             {"arn": b, "cambios": {"Owner": "pepe"}, "base": {"Owner": "luis"}}]
    plan = post(c, "/api/plan", {"items": items}).get_json()
    assert plan["account"] == CUENTA
    pa, pb = plan["plan"]
    assert pa["cambiar"] == {"Owner": ["ana", "pepe"]} and pa["borrar"] == {"Tmp": "1"} and pa["crear"] == {"Environment": "prod"}
    assert pb["conflictos"][0]["ahora"] == "marta" and pb["estado"] == "conflicto"
    assert plan["resumen"]["recursos"] == 1

    # Sin la confirmación exacta no se aplica
    r = post(c, "/api/aplicar", {"items": items, "confirmacion": "APLICAR"})
    assert r.status_code == 400 and CUENTA in r.get_json()["error"]
    assert nube.tags(a)["Owner"] == "ana"

    res = post(c, "/api/aplicar", {"items": items, "confirmacion": f"APLICAR EN {CUENTA}"}).get_json()
    assert nube.tags(a) == {"Owner": "pepe", "Environment": "prod"}
    assert nube.tags(b) == {"Owner": "marta"}
    assert [x["estado"] for x in res["resultados"]] == ["aplicado"]
    # La instantánea y el historial quedan al día
    snap = {r["arn"]: r for r in almacen.leer_snapshot(datos_dir)["recursos"]}
    assert snap[a]["tags"] == {"Owner": "pepe", "Environment": "prod"}
    lotes = get(c, "/api/historial").get_json()["lotes"]
    assert lotes[0]["id"] == res["lote"]
    assert lotes[0]["cambios"][0]["antes"] == {"Owner": "ana", "Environment": None, "Tmp": "1"}

    # Deshacer: mismo camino (revisar y aplicar), enlazado al lote que deshace
    deshacer = get(c, f"/api/historial/{res['lote']}/deshacer").get_json()["items"]
    r = post(c, "/api/aplicar", {"items": deshacer, "confirmacion": f"APLICAR EN {CUENTA}", "deshace": res["lote"]})
    assert r.status_code == 200
    assert nube.tags(a) == {"Owner": "ana", "Tmp": "1"}
    assert get(c, "/api/historial").get_json()["lotes"][0]["deshace"] == res["lote"]


def test_deshacer_con_conflicto(entorno):
    c, nube, _ = entorno
    a = nube.poner(arn_ec2(1), R, {"Owner": "ana"})
    leer(c)
    items = [{"arn": a, "cambios": {"Owner": "pepe"}, "base": {"Owner": "ana"}}]
    lote = post(c, "/api/aplicar", {"items": items, "confirmacion": f"APLICAR EN {CUENTA}"}).get_json()["lote"]
    nube.tags(a)["Owner"] = "otro"   # alguien lo cambia después
    deshacer = get(c, f"/api/historial/{lote}/deshacer").get_json()["items"]
    plan = post(c, "/api/plan", {"items": deshacer}).get_json()
    assert plan["plan"][0]["estado"] == "conflicto"
    r = post(c, "/api/aplicar", {"items": deshacer, "confirmacion": f"APLICAR EN {CUENTA}", "deshace": lote})
    assert r.status_code == 400 and nube.tags(a) == {"Owner": "otro"}


def test_global_se_revisa_y_aplica_en_us_east_1(entorno):
    c, nube, _ = entorno
    iam = nube.poner(f"arn:aws:iam::{CUENTA}:role/x", "us-east-1", {"Owner": "ana"})
    leer(c)
    items = [{"arn": iam, "cambios": {"Owner": "luis"}, "base": {"Owner": "ana"}}]
    plan = post(c, "/api/plan", {"items": items}).get_json()["plan"][0]
    assert plan["region"] == "us-east-1" and plan["cambiar"] == {"Owner": ["ana", "luis"]}
    post(c, "/api/aplicar", {"items": items, "confirmacion": f"APLICAR EN {CUENTA}"})
    assert nube.tags(iam) == {"Owner": "luis"}


def test_importar_y_exportar(entorno):
    c, nube, _ = entorno
    a = nube.poner(arn_ec2(1), R, {"Owner": "ana", "Tmp": "1"})
    assert post(c, "/api/importar").status_code == 400
    leer(c)

    r = get(c, "/api/exportar?formato=xlsx")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    csv = get(c, "/api/exportar?formato=csv").get_data(as_text=True)
    assert csv.lstrip("﻿").startswith("nombre,id,servicio,region,arn,url,Name,Application,Environment,Owner,Tmp")

    contenido = f"arn;Owner;Tmp\n{a};LUIS;\n".encode("utf-8")
    r = c.post("/api/importar", data={"fichero": (io.BytesIO(contenido), "aws_inventory.csv")},
               headers=ORIGEN, base_url="http://127.0.0.1", content_type="multipart/form-data")
    assert r.get_json()["cambios"] == {a: {"Owner": "luis", "Tmp": None}}
    assert nube.tags(a) == {"Owner": "ana", "Tmp": "1"}  # importar no toca AWS


def test_ajustes(entorno, config):
    c, _, _ = entorno
    nueva = {**config, "regiones": ["eu-west-1", "eu-south-2"], "esquema": ["Name", "Owner"]}
    r = c.put("/api/config", json={"config": nueva}, headers=ORIGEN, base_url="http://127.0.0.1")
    assert r.status_code == 200 and r.get_json()["config"]["regiones"] == ["eu-west-1", "eu-south-2"]
    r = c.put("/api/config", json={"config": {**config, "esquema": []}}, headers=ORIGEN, base_url="http://127.0.0.1")
    assert r.status_code == 400 and r.get_json()["errores"]


def test_credenciales_caducadas(entorno):
    c, nube, _ = entorno
    nube.sts_falla = "ExpiredToken"
    r = get(c, "/api/cuenta")
    assert r.status_code == 400 and "sso login" in r.get_json()["error"]
