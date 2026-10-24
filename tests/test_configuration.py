from pathlib import Path

import pytest

from netstate.configuration import load_desired
from netstate.exceptions import DesiredStateError

ROOT = Path(__file__).parent.parent


def test_example_desired_state_loads():
    desired = load_desired(ROOT / "configs/router1.yaml")
    assert desired["hostname"] == "Router1"
    assert desired["acls"]["100"]["type"] == "extended"


def test_invalid_yaml_shape_fails_loudly(tmp_path: Path):
    target = tmp_path / "bad.yaml"
    target.write_text("- not\n- a mapping\n")
    with pytest.raises(DesiredStateError):
        load_desired(target)


def test_invalid_interface_address_fails_loudly(tmp_path: Path):
    target = tmp_path / "bad.yaml"
    target.write_text("hostname: R1\ninterfaces:\n  Gi0/0:\n    ipv4_address: 999.1.1.1\n")
    with pytest.raises(DesiredStateError):
        load_desired(target)


def test_non_contiguous_ipv4_mask_is_rejected(tmp_path: Path):
    target = tmp_path / "bad-mask.yaml"
    target.write_text("hostname: R1\ninterfaces:\n  Gi0/0:\n    ipv4_address: 192.168.1.1\n    ipv4_mask: 255.0.255.0\n")
    with pytest.raises(DesiredStateError, match="contiguous IPv4 subnet mask"):
        load_desired(target)


def test_invalid_acl_binding_direction_is_rejected(tmp_path: Path):
    target = tmp_path / "bad-binding.yaml"
    target.write_text(
        "hostname: R1\ninterfaces:\n  Gi0/0:\n    access_groups:\n      sideways: '100'\n"
    )
    with pytest.raises(DesiredStateError, match="direction must be 'in' or 'out'"):
        load_desired(target)


def test_acl_binding_numbers_are_normalized_to_strings(tmp_path: Path):
    target = tmp_path / "binding.yaml"
    target.write_text(
        "hostname: R1\ninterfaces:\n  Gi0/0:\n    access_groups:\n      in: 100\n"
    )
    desired = load_desired(target)
    assert desired["interfaces"]["Gi0/0"]["access_groups"] == {"in": "100"}
