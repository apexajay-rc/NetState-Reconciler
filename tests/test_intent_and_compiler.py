from pathlib import Path

import pytest

from netstate_reconciler.compiler import CompileError, compile_intent
from netstate_reconciler.intent import load_intent

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "config" / "intent.example.yaml"


def test_sample_intent_parses_and_compiles():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    configs = compile_intent(intent)
    by_name = {config.device: config for config in configs}
    assert set(by_name) == {"R1", "R2", "SW1", "SW2"}
    assert "router ospf 1" in by_name["R1"].commands
    assert "interface GigabitEthernet0/0.20" in by_name["R1"].commands
    assert "encapsulation dot1Q 20" in by_name["R1"].commands
    assert "ip access-list extended GUEST_TO_FINANCE" in by_name["R1"].commands
    assert "vlan 10" in by_name["SW1"].commands
    assert "switchport port-security" in by_name["SW1"].commands


def test_host_static_requires_gateway_and_valid_address():
    bad = """
routers:
  R1: {}
hosts:
  PC1:
    mode: static
    ipv4: 192.168.1.2/24
"""
    with pytest.raises(Exception):
        load_intent(bad)


def test_invalid_interface_is_rejected_by_compiler():
    intent = load_intent("""
routers:
  R1:
    interfaces:
      'GigabitEthernet0/0\\n reload':
        ipv4: 192.168.1.1/24
""")
    with pytest.raises(CompileError):
        compile_intent(intent)


def test_secret_never_accepts_newlines():
    intent = load_intent("""
routers:
  R1: {}
""")
    with pytest.raises(CompileError):
        compile_intent(intent, {"username": "admin", "user_secret": "Password123\\nreload"})


def test_ssh_hardening_requires_credentials():
    intent = load_intent("""
routers:
  R1: {}
""")
    with pytest.raises(CompileError):
        compile_intent(intent, {"username": "netadmin", "user_secret": ""})


def test_ssh_hardening_compiler_avoids_packet_tracer_invalid_inline_rsa_syntax():
    intent = load_intent("routers:\n  R1: {}\n")
    config = compile_intent(intent, {
        "username": "netadmin", "user_secret": "ExamplePass123!",
        "enable_secret": "AnotherPass123!",
    })[0]
    assert "ip domain-name netstate.local" in config.commands
    assert "ip ssh version 2" in config.commands
    assert "crypto key generate rsa modulus 1024" not in config.commands
