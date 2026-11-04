"""Exception hierarchy. The CLI turns every CouncilError into a clean message and exit code."""

from __future__ import annotations


class CouncilError(Exception):
    """Base class for all expected, user-facing failures."""


class ConfigError(CouncilError):
    """Missing or invalid configuration (environment variables, config files)."""


class DatabaseSetupError(CouncilError):
    """Database initialisation or migration failed."""


class CsvValidationError(CouncilError):
    """The portfolio CSV is unusable. Carries the full report so callers can print every issue."""

    def __init__(self, message: str, report: object | None = None) -> None:
        super().__init__(message)
        self.report = report


class DataValidationError(CouncilError):
    """External or stored data does not have the expected structure."""


class EdgarError(CouncilError):
    """SEC EDGAR retrieval failed."""


class EdgarNotFoundError(EdgarError):
    """EDGAR has no document for the requested CIK."""


class EdgarCacheError(EdgarError):
    """A cached response is missing metadata or fails its integrity check."""


class EvidenceError(CouncilError):
    """Evidence could not be recorded or verified."""


class ClaimRuleError(CouncilError):
    """A claim violates the typing rules (e.g. a FACT without verified evidence)."""


class NotFoundError(CouncilError):
    """A requested portfolio, session or claim does not exist."""
