from netstate_reconciler.config_drift import config_diff, config_digest, redact_config


def test_running_config_redacts_secrets_and_stable_digest():
    text = """Building configuration...
hostname R1
enable secret 5 $1$private
username admin privilege 15 secret 9 another-secret
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.252
end
"""
    redacted = redact_config(text)
    assert "$1$private" not in redacted
    assert "another-secret" not in redacted
    assert "hostname R1" in redacted
    assert config_digest(redacted) == config_digest(redact_config(text))


def test_running_config_diff_reports_changed_lines():
    diff = config_diff("hostname R1\nno ip domain-lookup\n", "hostname R1\nip domain-lookup\n", "R1")
    assert "-no ip domain-lookup" in diff
    assert "+ip domain-lookup" in diff


def test_error_output_redacts_prompt_prefixed_secret_lines():
    from netstate_reconciler.config_drift import redact_output
    cleaned = redact_output("R1(config)# username admin privilege 15 secret SuperSecret123")
    assert "SuperSecret123" not in cleaned
