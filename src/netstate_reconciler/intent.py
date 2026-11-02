from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import NetworkIntent


class IntentError(ValueError):
    pass


def load_intent(text: str) -> NetworkIntent:
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IntentError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise IntentError("The intent document must be a YAML mapping")
    try:
        return NetworkIntent.model_validate(data)
    except ValidationError as exc:
        details = "\n".join(
            f"- {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise IntentError(f"Intent validation failed:\n{details}") from exc


def load_intent_file(path: str | Path) -> NetworkIntent:
    return load_intent(Path(path).read_text(encoding="utf-8"))


def intent_to_yaml(intent: NetworkIntent) -> str:
    return yaml.safe_dump(intent.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
