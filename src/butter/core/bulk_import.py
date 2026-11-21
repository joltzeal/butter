"""Strict parser for bulk account imports.

The operator pastes one account per line in this shape::

    inbox@example.com----account-password----备注

Rules, deliberately strict so a malformed paste fails loudly instead of
silently creating half-broken rows:

* exactly three fields separated by ``----`` (four hyphens)
* field 1 must look like an email address
* field 2 is the password: non-empty, no separator inside
* field 3 is the free-form note and may be empty
* blank lines and ``#`` comments are skipped; duplicates within the paste are dropped
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEP = "----"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


@dataclass
class ParsedAccount:
    email: str
    password: str
    note: str = ""
    line: int = 0


@dataclass
class ParseError:
    line: int
    text: str
    reason: str


@dataclass
class ParseResult:
    accounts: list[ParsedAccount]
    errors: list[ParseError]

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_bulk(text: str) -> ParseResult:
    """Parse a multi-line paste. Every bad line is reported, not skipped."""
    accounts: list[ParsedAccount] = []
    errors: list[ParseError] = []
    seen: set[str] = set()

    for index, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        fields = [part.strip() for part in line.split(SEP)]
        if len(fields) != 3:
            errors.append(
                ParseError(index, line, f"需要 3 段（邮箱{SEP}密码{SEP}备注），实际 {len(fields)} 段")
            )
            continue

        email, password, note = fields
        if not EMAIL_RE.match(email):
            errors.append(ParseError(index, line, f"邮箱格式不正确: {email or '(空)'}"))
            continue
        if not password:
            errors.append(ParseError(index, line, "密码为空"))
            continue

        key = email.lower()
        if key in seen:
            errors.append(ParseError(index, line, f"同一批中重复的邮箱: {email}"))
            continue
        seen.add(key)
        accounts.append(ParsedAccount(email=email, password=password, note=note, line=index))

    return ParseResult(accounts=accounts, errors=errors)
