"""Helpers shared by the hiring-team scripts.

Named shared.py, not common.py, so it never shadows tailor-resume's module
when both script folders are on the path.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
REFERENCES = SKILL_DIR / "references"
USER_AGENT = "hiring-team-skill/1.0"

# G1: the skill never fetches these hosts. Links to them are for the user to open.
BLOCKED_HOSTS = ("linkedin.com", "licdn.com", "lnkd.in")


@dataclass
class Finding:
    rule: str
    severity: str  # block or warn
    message: str
    where: str = ""
    value: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(data: Any, path: str | Path | None = None) -> str:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")
    return text


def today() -> _dt.date:
    """Today's date. HIRING_TEAM_TODAY=YYYY-MM-DD overrides it, for tests and replays."""
    override = os.environ.get("HIRING_TEAM_TODAY")
    return _dt.date.fromisoformat(override) if override else _dt.date.today()


def parse_date(value: Any) -> _dt.date | None:
    """ISO text, or epoch seconds or milliseconds, to a date."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return _dt.datetime.fromtimestamp(seconds, _dt.timezone.utc).date()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    return _dt.date(int(match[1]), int(match[2]), int(match[3])) if match else None


def add_working_days(start: _dt.date, days: int) -> _dt.date:
    """Monday to Friday only. Public holidays are not known here."""
    current = start
    while days > 0:
        current += _dt.timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")


def is_blocked_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_HOSTS)


# --------------------------------------------------------------------------
# Company names
# --------------------------------------------------------------------------

_SUFFIXES = (
    "incorporated", "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "gmbh", "plc", "lp", "llp", "pbc", "sa", "ag", "bv", "pty", "holdings",
)


def normalize_company(name: str) -> str:
    """ "Acme, Inc." -> "acme"; "AT&T" -> "at and t"."""
    text = ascii_fold(name).lower().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = text.split()
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def company_variants(name: str) -> set[str]:
    """The name itself plus any name inside brackets: "Amazon Web Services (AWS)"."""
    found = {normalize_company(name)}
    for inner in re.findall(r"\(([^)]+)\)", name or ""):
        found.add(normalize_company(inner))
    return {v for v in found if v}


def load_alias_groups(path: str | Path | None = None) -> list[set[str]]:
    file = Path(path) if path else REFERENCES / "company-aliases.json"
    if not file.is_file():
        return []
    return [{normalize_company(n) for n in group} for group in load_json(file).get("groups", [])]


def company_keys(name: str, groups: list[set[str]] | None = None) -> tuple[set[str], set[str]]:
    """(the company's own names, parent and brand names from the alias list)."""
    own = company_variants(name)
    related: set[str] = set()
    for group in groups if groups is not None else load_alias_groups():
        if own & group:
            related |= group
    return own, related - own


def company_match(candidate: str, own: set[str], related: set[str]) -> str:
    """ "exact", "related" (parent or brand) or "" for a connection's company text."""
    variants = company_variants(candidate)

    def hit(keys: set[str]) -> bool:
        for variant in variants:
            for key in keys:
                if variant == key:
                    return True
                # "google cloud" belongs to "google"; short keys must match whole.
                if len(key) >= 4 and variant.startswith(key + " "):
                    return True
        return False

    if hit(own):
        return "exact"
    if hit(related):
        return "related"
    return ""


def find_tailor_resume() -> Path | None:
    """The tailor-resume skill folder, when it is installed next to this one."""
    candidates = [os.environ.get("TAILOR_RESUME_DIR", "")]
    candidates += [
        str(SKILL_DIR.parent / "tailor-resume"),
        str(SKILL_DIR.parent.parent / "Tailor-Resume-Skill" / "tailor-resume"),
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "SKILL.md").is_file():
            return Path(candidate)
    return None
