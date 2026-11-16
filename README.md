# hiring-team-finder

A Claude skill that takes one job posting and returns the 3 people most worth contacting about it: the likely hiring manager, the recruiter and the best referral path. For each one it gives a short reason, a link to confirm who they are, ranked guesses at their work email and a drafted note saved to Gmail drafts. You pick the person and press send.

It reads the same `job.json` and tailored resume as [tailor-resume](https://github.com/maazin/Tailor-Resume-Skill), checks your own network before anyone cold, and never logs in to, crawls or reads LinkedIn pages.

Claude does the judgment (which team, which titles, who a search result is, what to say). Python scripts do everything that must be repeatable.

## Layout

```
hiring-team/        the skill: SKILL.md, references/, scripts/, tests/
```

Your own data stays out of this repo, in the same folder tailor-resume uses:

```
Resume Lab/
├── master.tex, confirmed-skills.md
├── Connections.csv       LinkedIn export of your connections
├── contacts.csv          optional club contacts
├── outreach.csv          one row per person contacted
├── cache/email-format/   one file per company, kept 90 days
└── applications/<company>-<role>/   job.json, posting.json, targets.json, ranked.json, hiring-team.md, notes/
```

## Requirements

Python 3.11+ and `pip install -r hiring-team/requirements.txt` (dnspython, for the MX lookup).

## Tests

```bash
python -m pytest hiring-team/tests
```

The tests use made-up people, companies and postings and make no network calls.

## Rules the code enforces

| Set | What | Script |
| --- | --- | --- |
| G1 | No linkedin.com page is ever fetched; page scans stay on the company's own public hosts | `shared.py`, `email_format.py` |
| G2 | At most 6 searches per posting, each once | `searches.py log` |
| G3 | Email guesses come from evidence and DNS MX only; no mail-server checks | `email_format.py` |
| G6 | 3 people per posting, 2 waiting at a time, one follow-up, a do-not-contact list | `outreach.py`, `rank.py` |
| M1 to M11 | Message rules: exact job in the first line, two proof points, one easy question, length limits | `note_check.py` |
| W1, W2, W8, W10 and the fact gate | No dashes, banned words or markup; every number and skill traces to `master.tex` | `note_check.py` |

Sending is not in the code at all: notes become Gmail drafts through Claude's Gmail connector, and SKILL.md forbids the send tools.

## Credits

Methods from HireLine, Hunterly, Email Pattern Finder, Find My Rec, Referral Finder, Recruiter Finder, LinkedIn Network Visualizer and career-ops. No code is copied; see `hiring-team/THIRD_PARTY.md`.
