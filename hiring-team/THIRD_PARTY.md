# Third-party sources

No upstream code is copied into this skill. Every script was written from scratch in Python from the methods described in the PRD, which lists what was read in each project on 2026-11-14. Projects with no license file were read for ideas only (G9 in the PRD). If code from an MIT project is copied in later, add its license text under `licenses/` and name the file and commit here.

| Source | License | Idea used | Where | What differs |
| --- | --- | --- | --- | --- |
| [HireLine](https://github.com/srikar0805/hireline) | None found | Function and seniority pick 2 manager and 2 recruiter titles, with university recruiters for entry level; people-search links; finding the email format by scanning /, /contact, /about, /team, /press and /privacy | `scripts/targets.py`, `scripts/searches.py`, `scripts/email_format.py` | Team names come from the ATS fields first. Page fetches are limited to the company's own public hosts |
| [Hunterly](https://github.com/Rishurajgautam24/hunterly) | MIT | A long email pattern list, learning a company's format from confirmed addresses, bounce handling that moves to the next guess, a message cap, a do-not-contact list | `scripts/email_format.py`, `scripts/outreach.py` | Pattern list written independently. No mail-server check. No reading of LinkedIn profiles. One follow-up after 5 working days instead of day 4 and day 9 |
| [Email Pattern Finder](https://github.com/apifyforge/email-pattern-finder) | MIT | Confidence = share of known name and email pairs that match a pattern; filters for role inboxes and junk addresses | `scripts/email_format.py` | Runs once per company and caches for 90 days. GitHub commit emails and domain registration records are not used in v1 |
| [Find My Rec](https://github.com/twixter51/Find-My-Recruiter) | None found | Searching posts where new hires thank their recruiter | search 4 in `scripts/searches.py` | Treated as a lead, never proof of who owns the posting |
| [Referral Finder](https://github.com/ppranav03/resume_extension) | None found | The alumni search `site:linkedin.com/in <company> <role> <university>` | search 5 in `scripts/searches.py` | Adds a club variant |
| [Recruiter Finder](https://github.com/shawnbatnagar/recruiter-finder) | MIT | Results are leads the user confirms; a reusable per-company cache | `scripts/rank.py`, `scripts/email_format.py` | The cache is local, not crowdsourced |
| [LinkedIn Network Visualizer](https://github.com/mstatt/LinkedIn-Network-Visualizer) | None found | Reading the `Connections.csv` export | `scripts/network.py` | Matches against the target company instead of drawing a graph |
| [career-ops](https://github.com/career-ops-hq/career-ops) | MIT | Joining the connections export against a company list | `scripts/network.py` | Adds parent and brand names |
| [Boolean Strings](https://booleanstrings.com/2022/07/25/how-to-x-ray-for-hiring-managers/) | Article | `inanchor:hiring` for managers who say they are hiring | search 2 | One of the 6 searches |
| [Careery](https://careery.pro/blog/networking/how-to-find-hiring-manager-for-job-posting) | Article | Recently hired peers, company team pages | `scripts/targets.py` (`peer_title`), SKILL.md step 5 | Peers become referral candidates |
| [FindHR](https://findhr.io/) | Closed source | Checking a posting's age before any lookup | `scripts/posting.py` | Idea only |
| [SimplifyJobs listings.json](https://github.com/SimplifyJobs/New-Grad-Positions) | Data file | `date_posted`, `date_updated`, `active` as a second date check | `scripts/posting.py --simplify` | Read from a file the user downloads; nothing is bundled |

The message rules M1 to M11 rest on the sources listed in the PRD: Hunter and Gong on length, Simplify and Happenstance on referrals and follow-ups, Careery on cold notes to managers, and LinkedIn's connection-note limits.

The writing rules W1, W2, W8 and W10 are tailor-resume's, re-implemented for a short note. Its `references/banned-words.txt` is read at run time when the two skills sit side by side.
