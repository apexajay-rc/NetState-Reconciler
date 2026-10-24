from pathlib import Path

from netstate.cli import main

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def test_audit_is_incomplete_when_security_sensitive_config_is_unmodeled(tmp_path: Path, capsys):
    source = tmp_path / "router-with-unmodeled-user.txt"
    raw = (FIXTURES / "router1_running.txt").read_text()
    raw = raw.replace("end\n", "username admin privilege 15 secret 5 REDACTED\nend\n")
    source.write_text(raw)

    result = main([
        "audit",
        "--desired", str(ROOT / "configs/router1.yaml"),
        "--source", str(source),
    ])

    output = capsys.readouterr().out
    assert result == 1
    assert "Status:  INCOMPLETE (PARSER WARNINGS)" in output
    assert "may affect security or routing" in output
