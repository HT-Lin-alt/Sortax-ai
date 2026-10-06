from pathlib import Path
from typing import Any

import yaml

from sortax.knowledge.models import KnowledgeManifest


def load_manifest(path: Path) -> KnowledgeManifest:
    """Load and validate a maintainer-authored ATO source manifest."""

    with path.open(encoding="utf-8") as manifest_file:
        raw: Any = yaml.safe_load(manifest_file)
    return KnowledgeManifest.model_validate(raw)
