from netstate.corpus_eval import evaluate

def test_version_labelled_corpus_evaluates_all_cases():
    result=evaluate('tests/corpus/manifest.yaml','configs/router1.yaml')
    assert len(result['cases']) == 3
    assert all(c['provenance']=='synthetic' for c in result['cases'])
    assert set(result['metrics']) >= {'false_positive_rate','false_negative_rate','precision','recall'}
