import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_aws import CUENTA, Nube  # noqa: E402

R = "eu-south-2"


def arn_ec2(i, region=R):
    return f"arn:aws:ec2:{region}:{CUENTA}:instance/i-{i:04d}"


@pytest.fixture
def nube():
    return Nube()


@pytest.fixture
def config():
    return {
        "perfil_aws": "",
        "regiones": [R],
        "servicios": ["s3", "iam", "kms"],
        "esquema": ["Name", "Application", "Environment", "Owner"],
        "catalogos": {"Environment": ["dev", "stg", "prod"]},
        "minusculas": True,
    }


@pytest.fixture
def config_path(tmp_path, config):
    from tagsx.core import config as core_config
    path = str(tmp_path / "tagsx_config.py")
    core_config.guardar(config, path)
    return path
