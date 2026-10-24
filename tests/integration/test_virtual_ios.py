"""Opt-in stateful integration test for an IOS-compatible SSH lab.

Set NETSTATE_LAB_HOST, NETSTATE_LAB_USERNAME, NETSTATE_DEVICE_PASSWORD and
NETSTATE_LAB_DESIRED to enable. This is not run against Packet Tracer by default.
"""
import os, pytest
from netstate.collectors.netmiko_collector import collect_from_ssh
from netstate.parsers.ios import CiscoIOSParser

@pytest.mark.skipif(not all(os.getenv(k) for k in ("NETSTATE_LAB_HOST","NETSTATE_LAB_USERNAME","NETSTATE_DEVICE_PASSWORD")), reason="IOS lab environment not configured")
def test_live_ios_collection_returns_parseable_config():
    text=collect_from_ssh(os.environ["NETSTATE_LAB_HOST"], os.environ["NETSTATE_LAB_USERNAME"], os.environ["NETSTATE_DEVICE_PASSWORD"], os.getenv("NETSTATE_LAB_DEVICE_TYPE","cisco_ios"), os.getenv("NETSTATE_ENABLE_SECRET",""), int(os.getenv("NETSTATE_LAB_PORT","22")))
    parser=CiscoIOSParser(); state=parser.parse(text)
    assert state.get("hostname")
    assert state.get("interfaces")
    assert not parser.warnings, f"Parser warnings in lab capture: {parser.warnings}"
