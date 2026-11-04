"""Keyword lint for advice-like language. The product gives considerations, never recommendations.

This is a safety net for generated text (including agent-written claims once those exist), not a
guarantee: it catches obvious phrasing only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("direct advice", re.compile(r"\byou (should|must|ought to|need to) (buy|sell|hold|add|trim|exit|accumulate|short)\b", re.I)),
    ("recommendation", re.compile(r"\b(we|i) (recommend|suggest|advise)\b", re.I)),
    ("rating", re.compile(r"\b(strong buy|strong sell|buy rating|sell rating|hold rating|outperform rating|underperform rating)\b", re.I)),
    ("price target", re.compile(r"\bprice target\b", re.I)),
    ("action call", re.compile(r"\b(a |the |is a |is an )?(buy|sell) (recommendation|signal|call)\b", re.I)),
    ("imperative", re.compile(r"\b(buy|sell) (now|today|immediately)\b", re.I)),
    ("guarantee", re.compile(r"\b(guaranteed (return|profit|gain)s?|risk[- ]free (return|profit))\b", re.I)),
)


@dataclass(frozen=True)
class LintFinding:
    rule: str
    excerpt: str


def lint_advice_language(markdown: str) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for rule, pattern in _PATTERNS:
        for match in pattern.finditer(markdown):
            findings.append(LintFinding(rule, match.group(0)))
    return findings
