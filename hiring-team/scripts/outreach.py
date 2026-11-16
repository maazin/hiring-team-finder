"""Outreach tracking: one row per person in "Resume Lab/outreach.csv".

The skill never sends (G4). The user sends a draft, then says so; this script
records it and works out when the single follow-up is due (G6, M11).

  status: drafted, sent, replied, bounced, no reply, do not contact

Commands:
  add       a drafted note for one person. Refuses a 4th person on one posting
            and anyone on the do-not-contact list.
  sent      the user sent it: sets sent_on and follow_up_on (5 working days later).
            Refuses when 2 notes for this posting are already waiting on a reply.
  due       rows whose follow-up check is due. For each, Claude searches Gmail
            for a reply or a delivery failure in that thread.
  replied   a reply arrived: closes the row; --from-email teaches the company's format.
  bounced   a delivery failure: marks the guess wrong and moves to the next
            guess (status back to drafted), or "bounced" after 3 guesses have failed.
  followup  the one follow-up was drafted: records it and closes the row as "no reply".
            A second follow-up is refused.
  dnc       do not contact, for this person at any company.
  list      rows, optionally for one company or job.

CLI:
  outreach.py --csv "Resume Lab/outreach.csv" add --company Acme --job-id R-4471 --job-url URL \
      --name "Jane Doe" --title "Engineering Manager" --slot manager --profile-url URL --path alumni \
      --email jane.doe@acme.com --email-confidence best
  outreach.py --csv ... sent --company Acme --job-id R-4471 --name "Jane Doe" [--on 2026-11-16]
  outreach.py --csv ... due [--on 2026-11-23]
  outreach.py --csv ... bounced --company Acme --job-id R-4471 --name "Jane Doe" --domain acme.com --cache-dir DIR
Exit code 1 when a rule refuses the change.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

from shared import add_working_days, dump_json, normalize_company, parse_date, today

COLUMNS = (
    "company", "job_id", "job_url", "name", "title", "slot", "profile_url", "path", "email", "email_confidence",
    "status", "sent_on", "follow_up_on", "follow_up_sent_on", "bounced_emails",
)
STATUSES = ("drafted", "sent", "replied", "bounced", "no reply", "do not contact")
MAX_PEOPLE = 3  # per posting (G6)
MAX_WAITING = 2  # messaged 1 or 2 at a time
FOLLOW_UP_WORKING_DAYS = 5
MAX_GUESSES = 3  # email guesses tried per person before the row closes as bounced


class Refused(ValueError):
    pass


def read_rows(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).is_file():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [{column: (row.get(column) or "").strip() for column in COLUMNS} for row in csv.DictReader(handle)]


def write_rows(path: str | Path, rows: list[dict[str, str]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _same_posting(row: dict[str, str], company: str, job_id: str) -> bool:
    return normalize_company(row["company"]) == normalize_company(company) and row["job_id"].lower() == job_id.lower()


def _find(rows: list[dict[str, str]], company: str, job_id: str, name: str) -> dict[str, str]:
    for row in rows:
        if _same_posting(row, company, job_id) and row["name"].lower() == name.strip().lower():
            return row
    raise Refused(f"no row for {name} on {company} {job_id}; add it first")


def is_do_not_contact(rows: list[dict[str, str]], name: str, profile_url: str = "") -> bool:
    for row in rows:
        if row["status"] != "do not contact":
            continue
        if row["name"].lower() == name.strip().lower() or (profile_url and row["profile_url"].lower() == profile_url.lower()):
            return True
    return False


def add(rows: list[dict[str, str]], **fields: str) -> dict[str, str]:
    company, job_id, name = fields["company"], fields["job_id"], fields["name"]
    if is_do_not_contact(rows, name, fields.get("profile_url", "")):
        raise Refused(f"{name} is on the do-not-contact list")
    posting_rows = [r for r in rows if _same_posting(r, company, job_id)]
    existing = next((r for r in posting_rows if r["name"].lower() == name.strip().lower()), None)
    if existing is None and len(posting_rows) >= MAX_PEOPLE:
        raise Refused(f"{MAX_PEOPLE} people are already tracked for {company} {job_id}; that is the cap per posting (G6)")
    row = existing or {column: "" for column in COLUMNS}
    row.update({k: str(v).strip() for k, v in fields.items() if k in COLUMNS and v is not None})
    row["status"] = row["status"] if existing and row["status"] != "drafted" else "drafted"
    if existing is None:
        rows.append(row)
    return row


def mark_sent(rows: list[dict[str, str]], company: str, job_id: str, name: str, on: _dt.date | None = None) -> dict[str, str]:
    row = _find(rows, company, job_id, name)
    if row["status"] == "do not contact":
        raise Refused(f"{name} is on the do-not-contact list")
    waiting = [r for r in rows if _same_posting(r, company, job_id) and r["status"] == "sent" and r is not row]
    if len(waiting) >= MAX_WAITING:
        raise Refused(f"{MAX_WAITING} notes for this posting are still waiting on a reply; message 1 or 2 people at a time (G6)")
    sent_on = on or today()
    row.update({
        "status": "sent", "sent_on": sent_on.isoformat(),
        "follow_up_on": add_working_days(sent_on, FOLLOW_UP_WORKING_DAYS).isoformat(), "follow_up_sent_on": "",
    })
    return row


def due(rows: list[dict[str, str]], on: _dt.date | None = None) -> list[dict[str, str]]:
    day = on or today()
    return [
        r for r in rows
        if r["status"] == "sent" and not r["follow_up_sent_on"] and (parse_date(r["follow_up_on"]) or _dt.date.max) <= day
    ]


def mark_replied(
    rows: list[dict[str, str]], company: str, job_id: str, name: str, from_email: str = "",
    domain: str = "", cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    row = _find(rows, company, job_id, name)
    row["status"] = "replied"
    learned = False
    if from_email and cache_dir:
        from email_format import clean_domain, learn

        target = clean_domain(domain or from_email.split("@")[-1])
        if from_email.lower().endswith("@" + target):
            try:
                learn(target, name, from_email, cache_dir)
                learned = True
            except ValueError:
                pass
        row["email"], row["email_confidence"] = from_email.lower(), "best"
    return {"row": row, "learned_format": learned}


def mark_bounced(
    rows: list[dict[str, str]], company: str, job_id: str, name: str, domain: str = "", cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Mark the current guess wrong and move to the next one."""
    row = _find(rows, company, job_id, name)
    wrong = row["email"]
    tried = [e for e in row["bounced_emails"].split(";") if e]
    if wrong and wrong not in tried:
        tried.append(wrong)
    row["bounced_emails"] = ";".join(tried)
    next_guess: dict[str, Any] | None = None
    if cache_dir and (domain or "@" in wrong):
        from email_format import clean_domain, guesses, record_bounce

        target = clean_domain(domain or wrong.split("@")[-1])
        state = record_bounce(target, name, wrong, cache_dir, row["email_confidence"]) if wrong else None
        if state and len(tried) < MAX_GUESSES:
            next_guess = next((g for g in guesses(name, state, count=6) if g["email"] not in tried), None)
    if next_guess:
        row.update({
            "email": next_guess["email"], "email_confidence": next_guess["label"], "status": "drafted",
            "sent_on": "", "follow_up_on": "", "follow_up_sent_on": "",
        })
    else:
        row.update({"email": "", "email_confidence": "", "status": "bounced"})
    return {"row": row, "wrong": wrong, "next_guess": next_guess, "redraft": bool(next_guess)}


def mark_followup(rows: list[dict[str, str]], company: str, job_id: str, name: str, on: _dt.date | None = None) -> dict[str, str]:
    row = _find(rows, company, job_id, name)
    if row["follow_up_sent_on"]:
        raise Refused(f"{name} already had the one follow-up on {row['follow_up_sent_on']}; stop here (M11)")
    if row["status"] != "sent":
        raise Refused(f"{name} is '{row['status']}', not waiting on a reply; no follow-up")
    row["follow_up_sent_on"] = (on or today()).isoformat()
    row["status"] = "no reply"  # the row closes; a later reply can still be recorded with `replied`
    return row


def mark_dnc(rows: list[dict[str, str]], company: str, job_id: str, name: str) -> dict[str, str]:
    row = _find(rows, company, job_id, name)
    row["status"] = "do not contact"
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="outreach.csv: one row per person")
    parser.add_argument("--csv", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    def person(p: argparse.ArgumentParser) -> None:
        p.add_argument("--company", required=True)
        p.add_argument("--job-id", required=True)
        p.add_argument("--name", required=True)

    a = sub.add_parser("add")
    person(a)
    for flag in ("job-url", "title", "slot", "profile-url", "path", "email", "email-confidence"):
        a.add_argument(f"--{flag}", default="")
    for name in ("sent", "followup"):
        p = sub.add_parser(name)
        person(p)
        p.add_argument("--on", default="")
    person(sub.add_parser("dnc"))
    r = sub.add_parser("replied")
    person(r)
    r.add_argument("--from-email", default="")
    b = sub.add_parser("bounced")
    person(b)
    for p in (r, b):
        p.add_argument("--domain", default="")
        p.add_argument("--cache-dir")
    d = sub.add_parser("due")
    d.add_argument("--on", default="")
    ls = sub.add_parser("list")
    ls.add_argument("--company", default="")
    ls.add_argument("--job-id", default="")
    args = parser.parse_args(argv)

    rows = read_rows(args.csv)
    on = parse_date(getattr(args, "on", "")) if getattr(args, "on", "") else None
    try:
        if args.command == "add":
            result: Any = add(
                rows, company=args.company, job_id=args.job_id, name=args.name, job_url=args.job_url, title=args.title,
                slot=args.slot, profile_url=args.profile_url, path=args.path, email=args.email,
                email_confidence=args.email_confidence,
            )
        elif args.command == "sent":
            result = mark_sent(rows, args.company, args.job_id, args.name, on)
        elif args.command == "followup":
            result = mark_followup(rows, args.company, args.job_id, args.name, on)
        elif args.command == "dnc":
            result = mark_dnc(rows, args.company, args.job_id, args.name)
        elif args.command == "replied":
            result = mark_replied(rows, args.company, args.job_id, args.name, args.from_email, args.domain, args.cache_dir)
        elif args.command == "bounced":
            result = mark_bounced(rows, args.company, args.job_id, args.name, args.domain, args.cache_dir)
        elif args.command == "due":
            print(dump_json(due(rows, on)), end="")
            return 0
        else:
            print(dump_json([
                r for r in rows
                if (not args.company or normalize_company(r["company"]) == normalize_company(args.company))
                and (not args.job_id or r["job_id"].lower() == args.job_id.lower())
            ]), end="")
            return 0
    except Refused as exc:
        print(f"outreach: {exc}", file=sys.stderr)
        return 1
    write_rows(args.csv, rows)
    print(dump_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
