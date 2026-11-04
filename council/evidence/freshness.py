"""Configurable freshness heuristics.

The thresholds are APPLICATION HEURISTICS chosen to draw a human's attention to old figures.
They are not accounting, legal or regulatory standards and say nothing about whether a figure is
correct. They live in ``config/freshness.yaml`` and are copied into each research session so a
dossier always states which thresholds produced its STALE flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from council.edgar.models import FactEntry
from council.errors import ConfigError

LABEL = "application heuristics, not accounting or regulatory standards"
_KEYS = ("annual_max_age_days", "quarterly_max_age_days", "snapshot_max_age_days")


@dataclass(frozen=True)
class FreshnessConfig:
    annual_max_age_days: int
    quarterly_max_age_days: int
    snapshot_max_age_days: int

    def to_json(self) -> dict[str, Any]:
        return {
            "annual_max_age_days": self.annual_max_age_days,
            "quarterly_max_age_days": self.quarterly_max_age_days,
            "snapshot_max_age_days": self.snapshot_max_age_days,
            "label": LABEL,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> FreshnessConfig:
        return _build(data, "stored freshness configuration")


def _build(data: Any, where: str) -> FreshnessConfig:
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be a mapping")
    values: dict[str, int] = {}
    for key in _KEYS:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{where}: {key} must be a positive integer number of days, got {value!r}")
        values[key] = value
    unknown = set(data) - set(_KEYS) - {"label"}
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")
    return FreshnessConfig(**values)


def load_freshness_config(path: Path | str) -> FreshnessConfig:
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(f"Freshness config not found: {file_path}")
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{file_path} is not valid YAML: {exc}") from exc
    return _build(data, str(file_path))


@dataclass(frozen=True)
class FreshnessAssessment:
    flag: Literal["NONE", "STALE"]
    detail: str | None
    fact_age_days: int
    snapshot_age_days: int


def assess_freshness(
    entry: FactEntry, *, retrieved_at: datetime, session_date: date, cfg: FreshnessConfig
) -> FreshnessAssessment:
    """Flag a fact as STALE when its period or the snapshot itself is older than the thresholds.

    Annual-basis facts use the annual threshold; everything else (quarterly and sub-year
    year-to-date periods) uses the quarterly threshold.
    """
    fact_age = max((session_date - entry.end).days, 0)
    snapshot_age = max((session_date - retrieved_at.date()).days, 0)
    annual = entry.basis == "annual"
    limit = cfg.annual_max_age_days if annual else cfg.quarterly_max_age_days
    reasons: list[str] = []
    if fact_age > limit:
        reasons.append(
            f"period ended {entry.end.isoformat()}, {fact_age} days before the session "
            f"(heuristic limit {limit} days for {'annual' if annual else 'quarterly/sub-year'} data)"
        )
    if snapshot_age > cfg.snapshot_max_age_days:
        reasons.append(
            f"snapshot retrieved {retrieved_at.date().isoformat()}, {snapshot_age} days before the session "
            f"(heuristic limit {cfg.snapshot_max_age_days} days)"
        )
    if reasons:
        return FreshnessAssessment("STALE", "; ".join(reasons) + f" [{LABEL}]", fact_age, snapshot_age)
    return FreshnessAssessment("NONE", None, fact_age, snapshot_age)
