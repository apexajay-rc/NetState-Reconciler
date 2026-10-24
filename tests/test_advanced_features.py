from netstate.transactions import DeviceCapabilities, execute_transaction
from netstate.topology import validate_topology
from netstate.evaluation import measure

class FakeDriver:
    def __init__(self, verify=True, fail_apply=False): self.verify_result=verify; self.fail_apply=fail_apply; self.rolled=False
    def capture_checkpoint(self): return "checkpoint-1"
    def apply(self, commands):
        if self.fail_apply: raise RuntimeError("simulated apply failure")
    def rollback(self, checkpoint): self.rolled=True
    def verify(self): return self.verify_result

def test_transaction_requires_approval():
    caps=DeviceCapabilities(True, True, ("hostname ",))
    result=execute_transaction(FakeDriver(), ["hostname R1"], caps, approved=False)
    assert result.status == "BLOCKED"

def test_transaction_blocks_unsupported_command():
    caps=DeviceCapabilities(True, True, ("hostname ",))
    result=execute_transaction(FakeDriver(), ["reload"], caps, approved=True)
    assert result.status == "BLOCKED"

def test_transaction_rolls_back_after_verification_failure():
    caps=DeviceCapabilities(True, True, ("hostname ",))
    driver=FakeDriver(verify=False)
    result=execute_transaction(driver, ["hostname R1"], caps, approved=True)
    assert result.status == "ROLLED_BACK" and driver.rolled

def test_transaction_commits_when_verified():
    caps=DeviceCapabilities(True, True, ("hostname ",))
    result=execute_transaction(FakeDriver(), ["hostname R1"], caps, approved=True)
    assert result.status == "COMMITTED"

def test_topology_detects_duplicate_ip_and_unknown_endpoint():
    findings=validate_topology({"devices":[{"name":"R1","interfaces":[{"name":"Gi0/0","ipv4_address":"10.0.0.1","ipv4_mask":"255.255.255.0"}]},{"name":"R2","interfaces":[{"name":"Gi0/0","ipv4_address":"10.0.0.1","ipv4_mask":"255.255.255.0"}]}],"links":[{"a":"R1/Gi0/0","b":"NOPE/Gi0/1"}]})
    assert {f.invariant for f in findings} >= {"unique_ip_addresses", "link_endpoint_exists"}

def test_confusion_metrics():
    m=measure([True,False,False,True],[True,True,False,False])
    assert (m.true_positive,m.false_positive,m.true_negative,m.false_negative)==(1,1,1,1)
    assert m.false_positive_rate == 0.5 and m.false_negative_rate == 0.5
