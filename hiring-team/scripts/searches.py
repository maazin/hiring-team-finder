"""Step 4: the 6 searches (G2). targets.json -> searches.json, and a ledger that enforces the cap.

Every output is a plain search query and plain links. Claude runs the query
as an ordinary web search and reads only result titles and snippets; it never
fetches a linkedin.com page (G1). The user opens any result they want to check.

  1 manager    site:linkedin.com/in "Acme" ("Engineering Manager" OR "Data Engineering Manager") "Data Platform"
  2 hiring     site:linkedin.com/in "Acme" inanchor:hiring "data" -recruiter
  3 recruiter  site:linkedin.com/in "Acme" ("University Recruiter" OR ...)
  4 new_hires  site:linkedin.com/posts "Acme" ("excited to join" OR "accepted an offer") recruiter
  5 alumni     site:linkedin.com/in "Acme" "Data Engineer" ("University of South Florida" OR "SHPE")
  6 team       "Acme" "Data Platform" (engineering blog OR talk OR podcast)

CLI:
  searches.py render --targets targets.json -o searches.json [--profile profile.json]
  searches.py log --app APP_DIR --id manager      record one search before running it
Exit code 1 from `log` means the search already ran for this posting, or 6 have run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from network import load_profile
from shared import dump_json, load_json

MAX_SEARCHES = 6
ORDER = ("manager", "hiring", "recruiter", "new_hires", "alumni", "team")
SLOT_SEARCHES = {"manager": ("manager", "hiring", "team"), "recruiter": ("recruiter", "new_hires"), "referral": ("alumni",)}


def _q(text: str) -> str:
    return '"' + str(text).replace('"', "").strip() + '"'


def _any(terms: list[str]) -> str:
    terms = [t for t in dict.fromkeys(terms) if t]
    if not terms:
        return ""
    return _q(terms[0]) if len(terms) == 1 else "(" + " OR ".join(_q(t) for t in terms) + ")"


def _links(query: str) -> dict[str, str]:
    encoded = quote_plus(query)
    return {
        "google": f"https://www.google.com/search?q={encoded}",
        "bing": f"https://www.bing.com/search?q={encoded}",
        "duckduckgo": f"https://duckduckgo.com/?q={encoded}",
    }


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def render(targets: dict[str, Any], profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    profile = profile or load_profile(None)
    company = _q(targets["company"])
    team = targets.get("team", "")
    team_q = _q(team) if team and team != "unknown" else ""
    # "Engineering Manager, Data Platform" searches as the title plus the team.
    managers = [t.split(",")[0].strip() if team and t.endswith(team) else t for t in targets.get("manager_titles", [])]
    keyword = targets.get("function_keyword", "")
    schools = [profile.get("school", "")] + list(profile.get("groups", []))[:1]
    queries = {
        "manager": _join("site:linkedin.com/in", company, _any(managers), team_q),
        "hiring": _join("site:linkedin.com/in", company, "inanchor:hiring", _q(keyword) if keyword else "", "-recruiter"),
        "recruiter": _join("site:linkedin.com/in", company, _any(targets.get("recruiter_titles", []))),
        "new_hires": _join("site:linkedin.com/posts", company, '("excited to join" OR "accepted an offer")', "recruiter"),
        "alumni": _join("site:linkedin.com/in", company, _q(targets.get("peer_title", "")) if targets.get("peer_title") else "", _any(schools)),
        "team": _join(company, team_q or (_q(keyword) if keyword else ""), "(engineering blog OR talk OR podcast)"),
    }
    purpose = {
        "manager": "The manager of the named team",
        "hiring": "Managers whose headline says they are hiring",
        "recruiter": "Recruiters for this level",
        "new_hires": "New hires thanking their recruiter. A lead, never proof of who owns this posting",
        "alumni": "Alumni and club members in the same role, for a referral",
        "team": "The team's public footprint: blog authors, talks. Often a better first contact than the manager",
    }
    return [
        {"n": i + 1, "id": key, "purpose": purpose[key], "query": queries[key], "links": _links(queries[key])}
        for i, key in enumerate(ORDER)
    ]


def hand_search(slot: str, searches: list[dict[str, Any]]) -> list[dict[str, str]]:
    """What to search by hand when a slot is left empty."""
    wanted = SLOT_SEARCHES.get(slot, ())
    return [{"id": s["id"], "query": s["query"], "link": s["links"]["google"]} for s in searches if s["id"] in wanted]


def log_search(app_dir: str | Path, search_id: str) -> tuple[bool, str]:
    """Record one search. Refuses a repeat and a seventh (G2)."""
    if search_id not in ORDER:
        return False, f"unknown search '{search_id}'; the six are: {', '.join(ORDER)}"
    ledger = Path(app_dir) / "searches_run.json"
    run = load_json(ledger) if ledger.is_file() else []
    if search_id in run:
        return False, f"'{search_id}' already ran for this posting; reuse its results"
    if len(run) >= MAX_SEARCHES:
        return False, f"{MAX_SEARCHES} searches have already run for this posting (G2)"
    run.append(search_id)
    dump_json(run, ledger)
    return True, f"search {len(run)} of {MAX_SEARCHES}: {search_id}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The 6 search templates and their ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("render")
    r.add_argument("--targets", required=True)
    r.add_argument("--profile")
    r.add_argument("-o", "--output", default="searches.json")
    l = sub.add_parser("log")
    l.add_argument("--app", required=True)
    l.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    if args.command == "render":
        print(dump_json(render(load_json(args.targets), load_profile(args.profile)), args.output), end="")
        return 0
    ok, message = log_search(args.app, args.id)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
