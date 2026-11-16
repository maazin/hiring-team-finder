"""Step 2: who to look for. job.json + posting.json -> targets.json.

These are starting rules (the approach is HireLine's: function and seniority
pick 2 manager and 2 recruiter titles). Claude reviews targets.json and edits
it when the posting says something more specific.

  team            ATS field first, then the title, then "join the X team" lines, else "unknown"
  function        data engineering, machine learning, software engineering, ...
  seniority       entry, mid or senior
  manager_titles  2
  skip_titles     2; at companies under about 50 people the CTO or a founder instead
  recruiter_titles  university and early-career recruiters for entry level
  peer_title      the role itself, for referrals from people hired in the last 2 years
  named_people    names the user pasted from LinkedIn's hiring team box; they rank first

CLI:
  targets.py --job job.json [--posting posting.json] -o targets.json
             [--headcount 35] [--team "Data Platform"] [--hiring-team "Jane Doe:Engineering Manager"]...
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

from shared import dump_json, load_json

SMALL_COMPANY = 50

# Order matters: the first pattern that matches the title wins.
FUNCTIONS: list[dict[str, Any]] = [
    {
        "key": "data_engineering", "label": "Data engineering", "keyword": "data", "technical": True,
        "pattern": r"data engineer|analytics engineer|\betl\b|data platform|data infrastructure|data warehouse|database engineer",
        "manager": ["Engineering Manager", "Data Engineering Manager"],
        "skip": ["Director of Data Engineering", "Head of Data"],
    },
    {
        "key": "machine_learning", "label": "Machine learning", "keyword": "machine learning", "technical": True,
        "pattern": r"machine learning|\bml\b|\bmle\b|\bai\b|applied scientist|research engineer|research scientist|deep learning|\bnlp\b|computer vision",
        "manager": ["Engineering Manager", "Machine Learning Engineering Manager"],
        "skip": ["Director of Machine Learning", "Head of AI"],
    },
    {
        "key": "data_science", "label": "Data science", "keyword": "data science", "technical": True,
        "pattern": r"data scien|decision scien|statistician|quantitative (?:analyst|researcher)",
        "manager": ["Data Science Manager", "Manager, Data Science"],
        "skip": ["Director of Data Science", "Head of Data Science"],
    },
    {
        "key": "analytics", "label": "Analytics", "keyword": "analytics", "technical": True,
        "pattern": r"analyst|analytics|business intelligence|\bbi\b",
        "manager": ["Analytics Manager", "Manager, Business Intelligence"],
        "skip": ["Director of Analytics", "Head of Data"],
    },
    {
        "key": "infrastructure", "label": "Infrastructure", "keyword": "infrastructure", "technical": True,
        "pattern": r"devops|site reliability|\bsre\b|platform engineer|infrastructure|cloud engineer|systems engineer|production engineer",
        "manager": ["Engineering Manager", "Infrastructure Engineering Manager"],
        "skip": ["Director of Infrastructure", "Head of Platform"],
    },
    {
        "key": "security", "label": "Security", "keyword": "security", "technical": True,
        "pattern": r"security|appsec|infosec|penetration",
        "manager": ["Security Engineering Manager", "Manager, Security"],
        "skip": ["Director of Security", "CISO"],
    },
    {
        "key": "quality", "label": "Quality engineering", "keyword": "quality", "technical": True,
        "pattern": r"\bqa\b|quality assurance|quality engineer|\bsdet\b|test engineer|software engineer in test",
        "manager": ["QA Manager", "Engineering Manager"],
        "skip": ["Director of Quality Engineering", "Director of Engineering"],
    },
    {
        "key": "product", "label": "Product management", "keyword": "product", "technical": False,
        "pattern": r"product manager|product owner|\bapm\b|program manager",
        "manager": ["Group Product Manager", "Director of Product"],
        "skip": ["VP of Product", "Head of Product"],
    },
    {
        "key": "design", "label": "Design", "keyword": "design", "technical": False,
        "pattern": r"designer|\bux\b|\bui\b|user research",
        "manager": ["Design Manager", "Head of Design"],
        "skip": ["Director of Design", "VP of Design"],
    },
    {
        "key": "software_engineering", "label": "Software engineering", "keyword": "engineering", "technical": True,
        "pattern": r"software|developer|engineer|\bswe\b|\bsde\b|backend|back-end|frontend|front-end|full.?stack|programmer|mobile|ios|android",
        "manager": ["Engineering Manager", "Software Engineering Manager"],
        "skip": ["Director of Engineering", "VP of Engineering"],
    },
]
FALLBACK = {
    "key": "general", "label": "General", "keyword": "", "technical": False,
    "manager": ["Manager", "Team Lead"], "skip": ["Director", "Vice President"],
}

_ENTRY = re.compile(
    r"new[\s-]?grad|university|early[\s-]career|entry[\s-]level|junior|\bjr\b|associate|intern(?:ship)?\b|graduate|campus|apprentice|\bI\b|\b1\b",
    re.IGNORECASE,
)
_INTERN = re.compile(r"\bintern(?:ship)?\b|co-?op", re.IGNORECASE)
_SENIOR = re.compile(r"senior|\bsr\b|staff|principal|\blead\b|\bIII\b|\bIV\b|\bV\b|architect|distinguished", re.IGNORECASE)
_LEVEL_WORDS = re.compile(
    r"\b(?:new[\s-]?grad(?:uate)?|university(?:\s+grad(?:uate)?)?|early[\s-]career|entry[\s-]level|junior|jr\.?|senior|sr\.?|staff|"
    r"principal|lead|associate|intern(?:ship)?|graduate|campus|I{1,3}|IV|V|[1-5]|20\d\d)\b",
    re.IGNORECASE,
)
_REQ_TAIL = re.compile(r"\s*[-(,]?\s*\b(?:Req(?:uisition)?|Job ID|R-?\d|JR)\b.*$", re.IGNORECASE)
_PLACE_HINT = re.compile(r"\bremote\b|\bhybrid\b|\bonsite\b|\b[A-Z][a-z]+,\s*[A-Z]{2}\b|\bUS\b|\bUSA\b|\bUnited States\b|\bEMEA\b|\bAPAC\b", re.IGNORECASE)
_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA "
    "RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
_TEAM_LINE = re.compile(r"\b(?:join|joining|on|the|our)\s+(?:the\s+|our\s+)?([A-Za-z][A-Za-z&/+ -]{2,40}?)\s+team\b", re.IGNORECASE)
_REPORT_LINE = re.compile(r"\breport(?:s|ing)?\s+(?:directly\s+)?to\b|\byou(?:'ll| will)\s+report\b", re.IGNORECASE)
_GENERIC_TEAM = frozenset(
    "a an the our your this that whole entire same right great growing small large broader wider global talented "
    "diverse amazing world-class collaborative cross-functional hiring recruiting talent people leadership executive "
    "management interview dynamic fast-paced high-performing passionate dedicated incredible new team of as with and "
    "for to join joining on in core".split()
)


def detect_function(title: str) -> dict[str, Any]:
    for function in FUNCTIONS:
        if re.search(function["pattern"], title, re.IGNORECASE):
            return function
    return FALLBACK


def detect_seniority(title: str, requirements: dict[str, Any] | None = None) -> tuple[str, bool]:
    """("entry" | "mid" | "senior", is an internship)."""
    requirements = requirements or {}
    intern = bool(_INTERN.search(title))
    if _SENIOR.search(title):
        return "senior", False
    level = str(requirements.get("seniority_level") or "").lower()
    years = requirements.get("experience_years")
    if intern or _ENTRY.search(title) or level in ("entry", "junior", "intern", "new grad", "entry-level"):
        return "entry", intern
    if level in ("senior", "staff", "principal", "lead"):
        return "senior", False
    if isinstance(years, (int, float)) and years <= 1 and level in ("", "entry"):
        return "entry", False
    return "mid", False


def title_segments(title: str) -> list[str]:
    cleaned = _REQ_TAIL.sub("", title or "")
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    return [part.strip() for part in re.split(r"\s*,\s*|\s+[-|:@]\s+|\s+[–—]\s+", cleaned) if part.strip()]


def peer_title(title: str) -> str:
    """ "Data Engineer, New Grad, Data Platform" -> "Data Engineer"."""
    segments = title_segments(title)
    if not segments:
        return ""
    role = next((s for s in segments if detect_function(s) is not FALLBACK), segments[0])
    role = re.sub(r"\s{2,}", " ", _LEVEL_WORDS.sub(" ", role)).strip(" -,")
    return role or segments[0]


def team_from_title(title: str) -> str:
    """A trailing segment that is not the role, a level or a place."""
    segments = title_segments(title)
    places = {i for i, s in enumerate(segments) if s in _STATES}
    places |= {i - 1 for i in places if i > 1}  # "Austin, TX": the city goes with its state
    segments = [s for i, s in enumerate(segments) if i not in places]
    for segment in reversed(segments[1:]):
        stripped = _LEVEL_WORDS.sub(" ", segment).strip(" -,")
        if not stripped or _PLACE_HINT.search(segment):
            continue
        if detect_function(segment) is not FALLBACK and re.search(r"engineer|scientist|analyst|developer|manager|designer", segment, re.I):
            continue
        return stripped
    return ""


def team_from_description(text: str) -> str:
    """The most repeated "join the X team" name."""
    counts: Counter[str] = Counter()
    for match in _TEAM_LINE.finditer(text or ""):
        words = [w for w in match.group(1).split() if w.lower() not in _GENERIC_TEAM]
        if 1 <= len(words) <= 4:
            counts[" ".join(words).lower()] += 1
    if not counts:
        return ""
    name = counts.most_common(1)[0][0]
    return " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in name.split())


def report_lines(text: str) -> list[str]:
    lines = []
    for line in re.split(r"\n|(?<=[.!?])\s+", text or ""):
        line = line.strip(" -•")
        if line and _REPORT_LINE.search(line) and line not in lines:
            lines.append(line[:240])
    return lines[:3]


def recruiter_titles(seniority: str, intern: bool, technical: bool) -> list[str]:
    base = "Technical Recruiter" if technical else "Recruiter"
    if seniority == "entry":
        titles = ["University Recruiter", "Early Career Recruiter", base]
        return (["Campus Recruiter"] + titles) if intern else titles
    if seniority == "senior":
        return [f"Senior {base}", base, "Talent Acquisition Partner"]
    return [base, "Talent Acquisition Partner"]


def parse_named(values: list[str]) -> list[dict[str, str]]:
    people = []
    for value in values:
        name, _, title = value.partition(":")
        if name.strip():
            people.append({"name": name.strip(), "title": title.strip(), "source": "pasted LinkedIn hiring team"})
    return people


def build_targets(
    job: dict[str, Any], posting: dict[str, Any] | None = None, headcount: int | None = None,
    team_override: str = "", named: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    posting = posting or {}
    title = str(job.get("title") or "")
    description = str(job.get("description_text") or "")
    function = detect_function(title)
    seniority, intern = detect_seniority(title, job.get("requirements") or {})

    team, team_source = "", ""
    for value, source in (
        (team_override, "user"), (posting.get("team", ""), "ats"),
        (team_from_title(title), "title"), (team_from_description(description), "description"),
    ):
        if value:
            team, team_source = value, source
            break

    manager = list(function["manager"])
    if team and function is not FALLBACK and "," not in manager[0]:
        manager[0] = f"{manager[0]}, {team}"
    skip = list(function["skip"])
    small = headcount is not None and headcount < SMALL_COMPANY
    if small:
        skip = ["CTO", "Co-founder"] if function["technical"] else ["CEO", "Co-founder"]

    review: list[str] = []
    if function is FALLBACK:
        review.append("The title matched no function rule; write the manager and skip-level titles by hand.")
    if not team:
        review.append("No team found in the ATS fields, the title or the description.")
    if headcount is None:
        review.append("Company size unknown; under about 50 people, pass --headcount so the CTO or a founder replaces the skip level.")
    return {
        "company": job.get("company", ""),
        "title": title,
        "job_id": posting.get("job_id", ""),
        "job_url": job.get("url", ""),
        "function": function["label"],
        "function_key": function["key"],
        "function_keyword": function["keyword"],
        "seniority": seniority,
        "internship": intern,
        "team": team or "unknown",
        "team_source": team_source,
        "department": posting.get("department", ""),
        "report_to_lines": report_lines(description),
        "manager_titles": manager[:2],
        "skip_titles": skip[:2],
        "recruiter_titles": recruiter_titles(seniority, intern, function["technical"]),
        "peer_title": peer_title(title),
        "small_company": small,
        "named_people": named or [],
        "review": review,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="job.json -> targets.json")
    parser.add_argument("--job", required=True)
    parser.add_argument("--posting")
    parser.add_argument("-o", "--output", default="targets.json")
    parser.add_argument("--headcount", type=int)
    parser.add_argument("--team", default="")
    parser.add_argument("--hiring-team", action="append", default=[], help='"Name:Title" pasted from LinkedIn')
    args = parser.parse_args(argv)
    posting = load_json(args.posting) if args.posting and Path(args.posting).is_file() else {}
    targets = build_targets(load_json(args.job), posting, args.headcount, args.team, parse_named(args.hiring_team))
    print(dump_json(targets, args.output), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
