.PHONY: install test lint validate audit-baseline audit-drift plan-drift version

install:
	python -m pip install -e '.[dev]'

test:
	pytest -v

lint:
	ruff check src tests

validate:
	netstate validate --desired configs/router1.yaml

audit-baseline:
	netstate audit --desired configs/router1.yaml --source tests/fixtures/router1_running.txt

audit-drift:
	-netstate audit --desired configs/router1.yaml --source tests/fixtures/router1_with_drift.txt

plan-drift:
	-netstate plan --desired configs/router1.yaml --source tests/fixtures/router1_with_drift.txt --json-output reports/remediation-plan.json

version:
	netstate --version
