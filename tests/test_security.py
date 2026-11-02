from netstate_reconciler.security import assess_reachability


def test_reachability_assessment_positive():
    assessment = assess_reachability({"text": "Success rate is 100 percent (5/5)", "raw": {}, "content": [], "isError": False})
    assert assessment.reachable is True
    assert assessment.status == "REACHABLE"


def test_no_reply_is_not_claimed_as_proof_of_security():
    assessment = assess_reachability({"text": "Request timed out.", "raw": {}, "content": [], "isError": False})
    assert assessment.reachable is False
    assert "not, by itself, proof" in assessment.summary or "does not prove" in assessment.summary


def test_unrecognised_response_is_indeterminate():
    assessment = assess_reachability({"text": "Some message not parsed", "raw": {}, "content": [], "isError": False})
    assert assessment.reachable is None


def test_packet_loss_is_not_misclassified_as_reachable():
    assessment = assess_reachability({"text": "Success rate is 0 percent (0/5), 100 percent packet loss", "raw": {}, "content": [], "isError": False})
    assert assessment.reachable is False
