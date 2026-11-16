# Search templates

`searches.py render` fills these from `targets.json`. At most 6 searches run per posting, each once (G2). Log each with `searches.py log` before running it.

```text
1 manager    site:linkedin.com/in "Acme" ("Engineering Manager" OR "Data Engineering Manager") "Data Platform"
2 hiring     site:linkedin.com/in "Acme" inanchor:hiring "data" -recruiter
3 recruiter  site:linkedin.com/in "Acme" ("University Recruiter" OR "Early Career Recruiter" OR "Technical Recruiter")
4 new_hires  site:linkedin.com/posts "Acme" ("excited to join" OR "accepted an offer") recruiter
5 alumni     site:linkedin.com/in "Acme" "Data Engineer" ("University of South Florida" OR "SHPE")
6 team       "Acme" "Data Platform" (engineering blog OR talk OR podcast)
```

| Search | Feeds | How to read the results |
| --- | --- | --- |
| manager | manager slot | Title and team in the result title or snippet is `title_and_team`. Title alone is `title`. |
| hiring | manager slot | People whose headline says they are hiring. Check the function matches; `-recruiter` keeps recruiters out. |
| recruiter | recruiter slot | A recruiter for the right level ("University", "Early Career" for new grads) is `recruiter_level`. |
| new_hires | recruiter slot | New hires thanking a recruiter by name. A lead, never proof that recruiter owns this posting: `evidence` is `inferred` unless another result confirms it. |
| alumni | referral slot | Same school or club, in the posting's role. `warmth` is `alumni` or `club`. |
| team | manager or referral slot | Blog authors and speakers on the team's systems. Company pages and blogs may be read; LinkedIn pages may not. |

Rules for every search:

- Run it as one ordinary web search. No proxies, no rotation, no second try under a new wording.
- Read titles and snippets only. Never fetch a linkedin.com URL (G1).
- Each person kept needs a link the user can open.
- Skip a search the network match already answered: unused searches are fine.
- When a slot ends up empty, `rank.py` prints the matching query and link for the user to run by hand.

The school and groups in search 5 come from `Resume Lab/profile.json` (see `profile.example.json`). The first group is added to the search; the rest are matched through `contacts.csv`.
