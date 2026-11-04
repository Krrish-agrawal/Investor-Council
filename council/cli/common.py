"""Shared CLI helpers: error handling, date parsing, plain-text tables."""

from __future__ import annotations

import functools
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, TypeVar

import typer

from council.errors import CouncilError, CsvValidationError

log = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


def echo_err(message: str) -> None:
    typer.echo(message, err=True)


def cli_errors(func: F) -> F:
    """Turn expected failures into a clean message and exit code 1 (no traceback)."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except CsvValidationError as exc:
            echo_err(f"error: {exc}")
            report = exc.report
            for issue in getattr(report, "errors", []) or []:
                where = f"line {issue.line}" if issue.line else "file"
                echo_err(f"  {where}: {issue.message}")
            raise typer.Exit(1) from None
        except CouncilError as exc:
            echo_err(f"error: {exc}")
            raise typer.Exit(1) from None
        except typer.Exit:
            raise
        except KeyboardInterrupt:
            raise typer.Exit(130) from None
        except Exception as exc:  # noqa: BLE001 - last-resort guard; details go to the log
            log.exception("Unexpected failure")
            echo_err(f"unexpected error: {type(exc).__name__}: {exc} (run with --log-level DEBUG for details)")
            raise typer.Exit(2) from None

    return wrapper  # type: ignore[return-value]


def parse_iso_date(value: str | None, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"{option} must be YYYY-MM-DD, got {value!r}") from None


def format_table(headers: Sequence[str], rows: Sequence[Sequence[object]], *, right: Sequence[int] = ()) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]

    def fmt(row: Sequence[str]) -> str:
        return "  ".join(c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(row)).rstrip()

    lines = [fmt(list(headers)), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in cells]
    return "\n".join(lines)


def stdout_is_tty() -> bool:
    return sys.stdout.isatty()
