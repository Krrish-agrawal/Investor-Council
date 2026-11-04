"""MANIFEST.json for the frozen dataset: one entry per cached document."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from council.edgar.client import CacheMeta
from council.errors import EdgarCacheError

MANIFEST_NAME = "MANIFEST.json"


def build_manifest(edgar_dir: Path | str) -> dict[str, Any]:
    """Collect sidecar metadata for every cached document under ``edgar_dir``."""
    root = Path(edgar_dir)
    entries: list[dict[str, Any]] = []
    for meta_path in sorted(root.glob("CIK*/*.meta.json")):
        meta = CacheMeta.from_json(json.loads(meta_path.read_text(encoding="utf-8")))
        entries.append(
            {
                "path": str(meta_path.with_name(meta_path.name.replace(".meta.json", ".json")).relative_to(root)),
                "cik": meta.cik,
                "kind": meta.kind,
                "source_url": meta.url,
                "retrieved_at": meta.retrieved_at.isoformat(),
                "sha256": meta.sha256,
                "size_bytes": meta.size_bytes,
            }
        )
    return {
        "data_mode": "FROZEN_SNAPSHOT",
        "note": "Frozen SEC EDGAR responses; not live. Newer filings may exist.",
        "documents": entries,
    }


def write_manifest(edgar_dir: Path | str) -> Path:
    root = Path(edgar_dir)
    if not root.is_dir():
        raise EdgarCacheError(f"{root} does not exist")
    manifest = build_manifest(root)
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    path = root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
