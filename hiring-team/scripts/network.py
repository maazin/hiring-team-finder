"""Step 3: check the user's own network before anyone cold (G5).

Reads LinkedIn's Connections.csv export (Settings > Data privacy > Get a copy
of your data > Connections) and a local contacts.csv of club contacts. Nothing
here touches linkedin.com: the export is a file the user downloaded, and the
alumni page is a link the user opens.

  Connections.csv  First Name, Last Name, URL, Email Address, Company, Position, Connected On
                   (LinkedIn puts a few "Notes:" lines above the header)
  contacts.csv     name, group, company, title, profile_url      e.g. group = SHPE

Company names are normalised (Inc, LLC, punctuation dropped) and matched
through references/company-aliases.json for parent and brand names. Matches
in the same function rank first.

CLI:
  network.py --connections Connections.csv --targets targets.json -o network.json
             [--contacts contacts.csv] [--profile profile.json] [--aliases aliases.json] [--refresh]
A second run with unchanged input files reuses network.json ("cached": true).
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from shared import REFERENCES, company_keys, company_match, dump_json, load_alias_groups, load_json
from targets import detect_function

DEFAULT_PROFILE = {
    "school": "University of South Florida", "school_short": "USF",
    "school_linkedin_slug": "university-of-south-florida", "groups": ["SHPE", "Data Science Club"],
}


def load_profile(path: str | Path | None) -> dict[str, Any]:
    profile = dict(DEFAULT_PROFILE)
    if path and Path(path).is_file():
        profile.update({k: v for k, v in load_json(path).items() if k != "note"})
    return profile


def read_connections(path: str | Path) -> list[dict[str, str]]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lower().startswith("first name")), None)
    if start is None:
        raise ValueError(f"{path} has no 'First Name,Last Name,...' header; is it LinkedIn's Connections.csv?")
    rows = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        name = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}".strip()
        if not name:
            continue
        rows.append({
            "name": name,
            "profile_url": (row.get("URL") or "").strip(),
            "company": (row.get("Company") or "").strip(),
            "title": (row.get("Position") or "").strip(),
            "connected_on": (row.get("Connected On") or "").strip(),
        })
    return rows


def read_contacts(path: str | Path | None) -> list[dict[str, str]]:
    if not path or not Path(path).is_file():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (row.get(key) or "").strip() for key in ("name", "group", "company", "title", "profile_url")}
            for row in csv.DictReader(handle) if (row.get("name") or "").strip()
        ]


def alumni_link(company: str, profile: dict[str, Any]) -> str:
    """The school's LinkedIn alumni page with the company as the keyword. The user opens it."""
    return f"https://www.linkedin.com/school/{profile['school_linkedin_slug']}/people/?keywords={quote_plus(company)}"


def _person(row: dict[str, str], match: str, warmth: str, function_key: str, path: str) -> dict[str, Any]:
    same_function = bool(row["title"]) and detect_function(row["title"])["key"] == function_key
    recruiter = "recruit" in row["title"].lower() or "talent acquisition" in row["title"].lower()
    return {
        "name": row["name"],
        "title": row["title"],
        "company": row["company"],
        "profile_url": row["profile_url"],
        "company_match": match,
        "same_function": same_function,
        "path": path,
        # Ready for rank.py. Claude may raise closeness when a search shows more.
        "slot": "recruiter" if recruiter else "referral",
        "warmth": warmth,
        "closeness": "recruiter_level" if recruiter else ("peer" if same_function else "none"),
        "evidence": "title",
    }


def match_network(
    company: str, function_key: str, connections: list[dict[str, str]], contacts: list[dict[str, str]],
    groups: list[set[str]] | None = None,
) -> list[dict[str, Any]]:
    own, related = company_keys(company, groups)
    people: dict[str, dict[str, Any]] = {}
    for row in connections:
        match = company_match(row["company"], own, related)
        if match:
            person = _person(row, match, "direct", function_key, "direct connection")
            person["connected_on"] = row["connected_on"]
            people[row["name"].lower()] = person
    for row in contacts:
        match = company_match(row["company"], own, related)
        if match and row["name"].lower() not in people:  # a direct connection is the warmer path
            people[row["name"].lower()] = _person(row, match, "club", function_key, row["group"] or "club")
    return sorted(
        people.values(),
        key=lambda p: (not p["same_function"], p["warmth"] != "direct", p["company_match"] != "exact", p["name"].lower()),
    )


def _stamp(path: str | Path | None) -> list[Any]:
    if not path or not Path(path).is_file():
        return []
    stat = Path(path).stat()
    return [str(Path(path).resolve()), stat.st_mtime_ns, stat.st_size]


def run(
    company: str, function_key: str, connections_path: str | Path | None, contacts_path: str | Path | None = None,
    profile: dict[str, Any] | None = None, aliases_path: str | Path | None = None,
    output: str | Path | None = None, refresh: bool = False,
) -> dict[str, Any]:
    profile = profile or dict(DEFAULT_PROFILE)
    aliases_file = aliases_path or REFERENCES / "company-aliases.json"
    source = {
        "company": company, "function_key": function_key, "connections": _stamp(connections_path),
        "contacts": _stamp(contacts_path), "aliases": _stamp(aliases_file),
    }
    if output and Path(output).is_file() and not refresh:
        previous = load_json(output)
        if previous.get("source") == source:
            previous["cached"] = True
            return previous
    connections = read_connections(connections_path) if connections_path and Path(connections_path).is_file() else []
    result = {
        "company": company,
        "cached": False,
        "source": source,
        "connections_read": len(connections),
        "people": match_network(company, function_key, connections, read_contacts(contacts_path), load_alias_groups(aliases_file)),
        "alumni_page": alumni_link(company, profile),
        "missing": [] if connections else [
            "No Connections.csv: export it from LinkedIn (Settings > Data privacy > Get a copy of your data > Connections)."
        ],
    }
    if output:
        dump_json(result, output)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Connections.csv + targets.json -> network.json")
    parser.add_argument("--connections")
    parser.add_argument("--contacts")
    parser.add_argument("--targets", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--aliases")
    parser.add_argument("-o", "--output", default="network.json")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    targets = load_json(args.targets)
    result = run(
        targets["company"], targets.get("function_key", ""), args.connections, args.contacts,
        load_profile(args.profile), args.aliases, args.output, args.refresh,
    )
    print(dump_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
