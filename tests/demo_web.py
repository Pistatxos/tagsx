"""La web con una cuenta simulada (~120 recursos), para probarla sin tocar AWS:

    uv run python tests/demo_web.py [carpeta-temporal]

Usa la AWS simulada de los tests; la config, la instantánea y el historial van a la
carpeta temporal (por defecto, una nueva), nunca a ~/.xsoft."""
import os
import random
import sys
import tempfile
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_aws import CUENTA, Nube  # noqa: E402
from tagsx.core import config as core_config  # noqa: E402
from tagsx.web.app import crear_app  # noqa: E402

R = "eu-south-2"


def sembrar(nube):
    azar = random.Random(7)
    apps = ["web", "data", "core", "lab", "ai"]
    owners = ["plataforma", "datos", "producto", "seguridad"]

    def tags(nombre, completo=0.7):
        t = {"Name": nombre}
        if azar.random() < completo + 0.2:
            t["Application"] = azar.choice(apps)
        if azar.random() < completo + 0.15:
            t["Environment"] = azar.choice(["dev", "dev", "stg", "prod", "prod", "PROD", "pre"])
        if azar.random() < completo:
            t["Owner"] = azar.choice(owners)
        if azar.random() < completo - 0.2:
            t["Project"] = azar.choice(["portal", "etl", "facturacion", "interno"])
        if azar.random() < completo - 0.1:
            t["Service"] = azar.choice(["api", "worker", "frontend", "batch"])
        if azar.random() < completo:
            t["ManagedBy"] = azar.choice(["terraform", "terraform", "cloudformation", "manual", "Terraform"])
        if azar.random() < 0.25:
            t["PatchGroup"] = azar.choice(["linux-a", "linux-b"])
        if azar.random() < 0.2:
            t["CostCenter"] = azar.choice(["cc-100", "cc-200"])
        return t

    for i in range(18):
        nube.poner(f"arn:aws:ec2:{R}:{CUENTA}:instance/i-0{i:03d}a1b2c3d4e5f", R, tags(f"{azar.choice(apps)}-server-{i:02d}"))
        nube.poner(f"arn:aws:ec2:{R}:{CUENTA}:volume/vol-0{i:03d}9f8e7d6c5b", R, tags(f"vol-{i:02d}", 0.4))
    for i in range(10):
        nube.poner(f"arn:aws:ec2:{R}:{CUENTA}:security-group/sg-0{i:03d}aa11bb22cc", R, tags(f"sg-{azar.choice(apps)}-{i}", 0.5))
    for i in range(3):
        nube.poner(f"arn:aws:ec2:{R}:{CUENTA}:vpc/vpc-0{i:03d}ffee", R, tags(f"vpc-{['dev', 'stg', 'prod'][i]}", 0.9))
        nube.poner(f"arn:aws:ec2:{R}:{CUENTA}:subnet/subnet-0{i:03d}aabb", R, tags(f"subnet-privada-{i}", 0.6))
    for i in range(22):
        nube.poner(f"arn:aws:lambda:{R}:{CUENTA}:function:{azar.choice(apps)}-{azar.choice(['ingesta', 'export', 'avisos', 'login', 'pdf'])}-{i:02d}", R, tags(f"fn-{i:02d}"))
    for i in range(4):
        nube.poner(f"arn:aws:rds:{R}:{CUENTA}:cluster:{azar.choice(apps)}-db-{i}", R, tags(f"db-{i}", 0.85))
    for i in range(8):
        nube.poner(f"arn:aws:sqs:{R}:{CUENTA}:cola-{azar.choice(['eventos', 'pedidos', 'reintentos'])}-{i}", R, tags(f"cola-{i}", 0.5))
        nube.poner(f"arn:aws:sns:{R}:{CUENTA}:avisos-{i}", R, tags(f"avisos-{i}", 0.5))
    for i in range(6):
        nube.poner(f"arn:aws:dynamodb:{R}:{CUENTA}:table/tabla-{azar.choice(apps)}-{i}", R, tags(f"tabla-{i}"))
    for i in range(6):
        nube.poner(f"arn:aws:iam::{CUENTA}:role/rol-{azar.choice(['lambda', 'ecs', 'despliegue', 'lectura'])}-{i}", "us-east-1", tags(f"rol-{i}", 0.5))
    nube.poner(f"arn:aws:cloudfront::{CUENTA}:distribution/E2DEMO1234", "us-east-1", tags("cdn-portal", 0.9))
    for i, region in enumerate([R, R, "eu-west-1", R, R]):
        nube.buckets[f"demo-{['logs', 'datos', 'backups', 'web', 'tmp'][i]}"] = region
        nube.poner(f"arn:aws:s3:::demo-{['logs', 'datos', 'backups', 'web', 'tmp'][i]}", region, tags(f"demo-{i}", 0.6))
    nube.roles = ["rol-sin-etiquetas"]
    nube.poner(f"arn:aws:iam::{CUENTA}:role/rol-sin-etiquetas", "us-east-1")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    carpeta = args[0] if args else tempfile.mkdtemp(prefix="tagsx-demo-")
    config_path = os.path.join(carpeta, "tagsx_config.py")
    if not os.path.exists(config_path):
        config = core_config.config_plantilla()
        config["perfil_aws"] = "demo"
        config["servicios"] = ["s3", "iam"]
        config["catalogos"]["Application"] = ["web", "data", "core", "lab", "ai"]
        core_config.guardar(config, config_path)

    nube = Nube()
    sembrar(nube)
    app = crear_app(config_path=config_path, data_dir=os.path.join(carpeta, "datos"), token="demo",
                    sesion_factory=nube.sesion, perfiles_aws=["default", "demo"])

    from werkzeug.serving import make_server
    puerto = int(os.environ.get("PUERTO", "8799"))
    servidor = make_server("127.0.0.1", puerto, app, threaded=True)
    url = f"http://127.0.0.1:{puerto}/?token=demo"
    print(f"Demo en {url} (datos en {carpeta})", flush=True)
    if "--abrir" in sys.argv:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    servidor.serve_forever()


if __name__ == "__main__":
    main()
