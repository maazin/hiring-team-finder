"""Rank the people found and pick at most 3: one manager, one recruiter, one referral path.

Every person gets a score out of 100 from three parts, and the report shows
each part so the user can see why someone ranks where they do.

  warmth     direct connection 40 · alumni or same club 30 · peer with the same title 20 · cold 0
  closeness  named in the posting or its LinkedIn hiring team 40 · manager of the named team 35 ·
             recruiter for this level 30 · skip-level 20 · peer 15 · none 0
  evidence   title and team both in the search result 20 · title only 10 · inferred 0
             (for a recruiter, "team" means the level they recruit for, such as University)

A slot with nobody above 40 is left empty rather than filled with a weak
guess, and the report says what to search by hand. The numbers are starting
values to tune after 20 postings, based on who actually replied.

people.json is a list Claude writes from the network match and the search
results. Each person:
  {"name", "title", "company", "profile_url", "slot": "manager|recruiter|referral",
   "warmth": "direct|alumni|club|peer|cold", "closeness": "named|team_manager|recruiter_level|skip|peer|none",
   "evidence": "title_and_team|title|inferred", "found_by": "search id or network", "why": "one line"}

CLI:
  rank.py --people people.json -o ranked.json [--searches searches.json]
          [--outreach outreach.csv] [--report hiring-team.md] [--recruiter-first]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from shared import dump_json, load_json, normalize_company

WARMTH = {"direct": 40, "alumni": 30, "club": 30, "peer": 20, "cold": 0}
CLOSENESS = {"named": 40, "team_manager": 35, "recruiter_level": 30, "skip": 20, "peer": 15, "none": 0}
EVIDENCE = {"title_and_team": 20, "title": 10, "inferred": 0}
SLOTS = ("manager", "recruiter", "referral")
MIN_SCORE = 40  # a slot needs someone above this
MAX_PEOPLE = 3  # G6


def default_slot(person: dict[str, Any]) -> str:
    closeness, warmth = person.get("closeness", "none"), person.get("warmth", "cold")
    if closeness == "recruiter_level":
        return "recruiter"
    if closeness in ("named", "team_manager", "skip") and warmth in ("cold", "peer"):
        return "manager"
    if closeness in ("peer", "none"):
        return "referral"
    return "manager"


def score(person: dict[str, Any]) -> dict[str, Any]:
    problems = []
    for field, table in (("warmth", WARMTH), ("closeness", CLOSENESS), ("evidence", EVIDENCE)):
        if person.get(field) not in table:
            problems.append(f"{field} must be one of {', '.join(table)}")
    if not str(person.get("profile_url") or "").startswith(("http://", "https://")):
        problems.append("profile_url must be a link the user can open")
    parts = {
        "warmth": WARMTH.get(person.get("warmth"), 0),
        "closeness": CLOSENESS.get(person.get("closeness"), 0),
        "evidence": EVIDENCE.get(person.get("evidence"), 0),
    }
    slot = person.get("slot") if person.get("slot") in SLOTS else default_slot(person)
    return {**person, "slot": slot, "score": sum(parts.values()), "parts": parts, "problems": problems}


def blocked_people(outreach_csv: str | Path | None, company: str) -> tuple[set[str], set[str]]:
    """(do-not-contact keys anywhere, people already in the tracker for this company)."""
    never: set[str] = set()
    already: set[str] = set()
    if not outreach_csv or not Path(outreach_csv).is_file():
        return never, already
    with Path(outreach_csv).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            keys = {(row.get("name") or "").strip().lower(), (row.get("profile_url") or "").strip().lower()} - {""}
            if (row.get("status") or "").strip().lower() == "do not contact":
                never |= keys
            elif normalize_company(row.get("company") or "") == normalize_company(company):
                already |= keys
    return never, already


def rank(
    people: list[dict[str, Any]], searches: list[dict[str, Any]] | None = None,
    never: set[str] | None = None, recruiter_first: bool = False,
) -> dict[str, Any]:
    from searches import hand_search

    never = never or set()
    scored, skipped = [], []
    for person in people:
        row = score(person)
        keys = {str(row.get("name") or "").strip().lower(), str(row.get("profile_url") or "").strip().lower()} - {""}
        if keys & never:
            skipped.append({"name": row.get("name", ""), "reason": "on the do-not-contact list"})
        elif row["problems"]:
            skipped.append({"name": row.get("name", ""), "reason": "; ".join(row["problems"])})
        else:
            scored.append(row)
    scored.sort(key=lambda r: (-r["score"], -r["parts"]["warmth"], -r["parts"]["closeness"], str(r.get("name", "")).lower()))

    picks: dict[str, Any] = {}
    empty: list[dict[str, Any]] = []
    for slot in SLOTS:
        best = next((r for r in scored if r["slot"] == slot and r["score"] > MIN_SCORE), None)
        if best:
            picks[slot] = best
        else:
            closest = next((r for r in scored if r["slot"] == slot), None)
            empty.append({
                "slot": slot,
                "reason": f"nobody scored above {MIN_SCORE}"
                + (f"; closest was {closest['name']} at {closest['score']}" if closest else "; nobody found"),
                "search_by_hand": hand_search(slot, searches or []),
            })
    order = [s for s in (("recruiter", "referral", "manager") if recruiter_first else ("referral", "manager", "recruiter")) if s in picks]
    return {
        "picks": [picks[s] for s in SLOTS if s in picks][:MAX_PEOPLE],
        "contact_order": order,
        "contact_order_why": (
            "The posting is flagged as old or reposted: ask the recruiter first whether the role is still open."
            if recruiter_first else "Referral before applying; manager and recruiter after applying (M10). Message 1 or 2 at a time."
        ),
        "empty_slots": empty,
        "all_scored": scored,
        "skipped": skipped,
    }


def report(result: dict[str, Any], title: str = "") -> str:
    lines = [f"# Hiring team{': ' + title if title else ''}", ""]
    if result["picks"]:
        lines += ["| Slot | Person | Title | Score | Warmth | Closeness | Evidence | Link |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for p in result["picks"]:
            parts = p["parts"]
            lines.append(
                f"| {p['slot']} | {p.get('name', '')} | {p.get('title', '')} | {p['score']} | "
                f"{p['warmth']} {parts['warmth']} | {p['closeness']} {parts['closeness']} | "
                f"{p['evidence']} {parts['evidence']} | [profile]({p['profile_url']}) |"
            )
        lines.append("")
        for p in result["picks"]:
            if p.get("why"):
                lines.append(f"- **{p.get('name', '')}**: {p['why']}")
        lines += ["", f"Order: {', '.join(result['contact_order'])}. {result['contact_order_why']}", ""]
    for slot in result["empty_slots"]:
        lines.append(f"**No {slot['slot']} picked** ({slot['reason']}). Search by hand:")
        lines += [f"- [{s['id']}]({s['link']}): `{s['query']}`" for s in slot["search_by_hand"]] or ["- no search template for this slot"]
        lines.append("")
    if result["skipped"]:
        lines.append("Left out: " + "; ".join(f"{s['name']} ({s['reason']})" for s in result["skipped"]))
        lines.append("")
    lines.append("Every name is a lead. Open the link and confirm who they are before sending anything.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score people and pick one per slot")
    parser.add_argument("--people", required=True)
    parser.add_argument("--searches")
    parser.add_argument("--outreach")
    parser.add_argument("-o", "--output", default="ranked.json")
    parser.add_argument("--report")
    parser.add_argument("--recruiter-first", action="store_true", help="the posting was flagged in step 0")
    args = parser.parse_args(argv)
    people = load_json(args.people)
    searches = load_json(args.searches) if args.searches and Path(args.searches).is_file() else []
    company = str(people[0].get("company", "")) if people else ""
    never, _ = blocked_people(args.outreach, company)
    result = rank(people, searches, never, args.recruiter_first)
    dump_json(result, args.output)
    text = report(result)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
