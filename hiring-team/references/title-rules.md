# Title rules and people.json

## Reviewing targets.json

`targets.py` gives starting titles from the job title. Edit the file when the posting says more.

| Field | Rule |
| --- | --- |
| `team` | ATS field first (Greenhouse `departments`, Lever `categories.team`, Ashby `team`), then the job title, then "join the X team" lines. Keep `unknown` rather than guessing. |
| `manager_titles` | 2 titles. If a `report_to_lines` entry names a title ("reporting to the Director of Data"), put that title first. |
| `skip_titles` | 2 titles one level above the manager. Under about 50 people, the CTO or a founder. |
| `recruiter_titles` | Entry level and internships list university and early-career recruiters first. |
| `peer_title` | The role without level words. A peer who joined in the last 2 years is the referral candidate. |
| `named_people` | Names the user pasted from LinkedIn's hiring team box. They score `named`. |

Example for "Data Engineer, New Grad, Data Platform":

| Target | Value |
| --- | --- |
| Function and seniority | Data engineering, entry |
| Team | Data Platform |
| Manager titles | Engineering Manager, Data Platform; Data Engineering Manager |
| Skip-level titles | Director of Data Engineering; Head of Data |
| Recruiter titles | University Recruiter; Early Career Recruiter; Technical Recruiter |
| Peer title | Data Engineer |

## people.json

A list. One object per person, from `network.json` (copy those as they are) and from search results.

```json
{
  "name": "Jane Doe",
  "title": "Engineering Manager, Data Platform",
  "company": "Acme",
  "profile_url": "https://www.linkedin.com/in/janedoe",
  "slot": "manager",
  "warmth": "cold",
  "closeness": "team_manager",
  "evidence": "title_and_team",
  "found_by": "manager",
  "why": "Her headline names the Data Platform team at Acme."
}
```

| Field | Values | Points |
| --- | --- | --- |
| `warmth` | `direct` a first-degree connection in `Connections.csv` | 40 |
| | `alumni` same school, or `club` same club or society | 30 |
| | `peer` holds the posting's title, no other tie | 20 |
| | `cold` | 0 |
| `closeness` | `named` in the posting or its LinkedIn hiring team | 40 |
| | `team_manager` manages the named team | 35 |
| | `recruiter_level` recruits for this level | 30 |
| | `skip` one level above the manager | 20 |
| | `peer` same role on the team | 15 |
| | `none` at the company, nothing closer | 0 |
| `evidence` | `title_and_team` both appear in the result title or snippet | 20 |
| | `title` only the title appears | 10 |
| | `inferred` neither is stated | 0 |

Notes:

- For a recruiter, "team" in `evidence` means the level they recruit for. "University Recruiter at Acme" for a new-grad role is `title_and_team`; a plain "Recruiter at Acme" is `title`.
- `slot` is `manager`, `recruiter` or `referral`. A warm contact who is also the team's manager goes in `manager`; rank keeps their warmth points.
- `profile_url` must be a link the user can open. It comes from the search result. Never fetch it.
- `why` is one line the user can check against the link. Say what the snippet showed, nothing more.
- Leave out anyone whose snippet does not clearly place them at the company now ("former", "ex-", an end date).

A slot needs someone above 40 points. A cold recruiter with only a title scores 40 and is left out on purpose: the report then lists the recruiter search to run by hand.

The 40/35/30 numbers are starting values. Tune them after 20 postings from who actually replied (`outreach.csv`).
