"""Evaluate the labelled parser corpus against desired-state files.

The current bundled corpus is synthetic. Metrics are smoke-test results, not real-release accuracy.
"""
import argparse, json
from pathlib import Path
import yaml
from netstate.configuration import load_desired
from netstate.parsers.ios import CiscoIOSParser
from netstate.reconciler.diff import compare_states
from netstate.evaluation import measure

def evaluate(manifest_path: str, desired_path: str) -> dict:
    manifest_file=Path(manifest_path); manifest=yaml.safe_load(manifest_file.read_text())
    desired=load_desired(desired_path); labels=[]; predictions=[]; rows=[]
    for case in manifest.get('cases', []):
        source=manifest_file.parent / case['file']; parser=CiscoIOSParser(); actual=parser.parse(source.read_text())
        drifts=compare_states(desired, actual); predicted=bool(drifts or parser.warnings)
        label=bool(case['expected_drift']); labels.append(label); predictions.append(predicted)
        rows.append({'id':case['id'],'version_label':case['version_label'],'provenance':case.get('provenance','unknown'),
                     'expected_drift':label,'predicted_drift':predicted,'correct':label==predicted,
                     'drift_count':len(drifts),'parser_warnings':parser.warnings})
    metrics=measure(labels,predictions).to_dict()
    return {'corpus_version':manifest.get('corpus_version'), 'warning':manifest.get('provenance_policy'),
            'metrics':metrics,'cases':rows}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--manifest',default='tests/corpus/manifest.yaml'); p.add_argument('--desired',default='configs/router1.yaml'); p.add_argument('--output',default='reports/corpus-evaluation.json'); a=p.parse_args()
    result=evaluate(a.manifest,a.desired); out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result['metrics'],indent=2)); print(f"Wrote {out}")
if __name__=='__main__': main()
