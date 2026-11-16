# Note templates

A good note names the exact job in its first line, proves two things the posting cares about with real results, and asks one easy question, in under 100 words. Write the note as `note.json`, run `note_check.py`, and only then save the draft.

Every claim comes from `master.tex`. Numbers and tools are copied from the master, never rounded up or moved between jobs. Skills the user only confirmed (`confirmed-skills.md`) may be named but not given a made-up result.

## note.json

```json
{
  "kind": "manager",
  "to_name": "Jane Doe",
  "subject": "Data Engineer, R-4471",
  "greeting": "Hi Jane,",
  "body": "...",
  "signoff": "Thanks,\nFirst Last",
  "applied": true,
  "job_url": "https://boards.greenhouse.io/acme/jobs/4000001",
  "resume_url": "https://...",
  "knows_them": "the clause in the body that shows you know who they are",
  "attachments": []
}
```

Referral notes add `how_we_know` (a clause copied from the body) and `blurb`. Follow-ups add `new_fact` (a clause copied from the body). Word limits count the body only, not the greeting or sign-off.

## Shapes

| Kind | Shape | Body length |
| --- | --- | --- |
| `manager`, after applying | Job title and ID in the first sentence. Two sentences, each proving one of the posting's top 2 requirements with a number. One clause on their team. The resume link. One easy question, such as whether the team is still hiring for it. | 50 to 100 words |
| `recruiter`, after applying | Job title and ID. Two proof sentences. The resume link. Ask who owns the role if they do not. | 50 to 80 words |
| `referral`, before applying | How you know each other. Job title, ID and link. The resume link. Ask whether they prefer you apply first. A separate paste-ready blurb of 2 to 3 sentences for their referral form. | Under 100 words plus the blurb |
| `linkedin` | Job title, ID and one proof point. No question. Shown in chat for the user to paste. | 200 characters |
| `followup`, 5 working days later | One new fact (a shipped project, a new result) and at most one question. Sent once. | 15 to 60 words |

Subject line: 4 words or fewer, for example "Data Engineer, R-4471".

## Skeletons

Square brackets are slots to fill from the posting and the master resume. Do not keep the wording if a plainer sentence fits.

Manager:

```
I applied for the [exact title] role ([job ID]) on your [team] team. At [employer] I [did the thing requirement 1 asks for] [with a number]. I also [did the thing requirement 2 asks for] [with a number]. [One clause on their team, post or talk.] My resume is here: [resume link]. The posting is here: [job link]. Is the team still hiring for this role?
```

Recruiter:

```
I applied for the [exact title] role ([job ID]). At [employer] I [proof for requirement 1, with a number]. I also [proof for requirement 2, with a number]. My resume is here: [resume link]. If you are not the recruiter for this role, who should I contact?
```

Recruiter, when step 0 flagged the posting: swap the question for "Is this role still open?"

Referral:

```
[How you know each other, in one clause.] I plan to apply for the [exact title] role ([job ID]) at [company]: [job link]. My resume for it is here: [resume link]. Would you rather I apply first, or go through your referral form? A short blurb is below in case it helps.
```

Blurb (2 to 3 sentences, third person or first person, their form decides):

```
[Name] is a [degree, school, year] who [proof for requirement 1, with a number]. [Proof for requirement 2.] [How I know them.]
```

LinkedIn connection note:

```
I applied for the [exact title] role ([job ID]). At [employer] I [one proof point with a number].
```

Follow-up:

```
Since my note about the [exact title] role, [one new fact]. [Optional single question.]
```

## Rules the check enforces

| # | Rule |
| --- | --- |
| M1 | The first sentence names the exact job title and job ID |
| M2 | Two sentences, each proving a top requirement with a real result from the master resume, numbers included |
| M3 | No filler self-description: passionate, results-driven, hardworking, team player, go-getter, eager to learn |
| M4 | One clause shows you know who they are: their team, a post or talk, or how you are connected. Never their personal life |
| M5 | One question that can be answered in a line. Never "review my resume" or "30 minutes of your time" |
| M6 | Email body 50 to 100 words (recruiter 50 to 80). Subject 4 words or fewer |
| M7 | LinkedIn connection note: 200 characters or fewer, M1 and one proof point, no ask beyond connecting |
| M8 | No attachment. Link the tailored resume |
| M9 | Referral: one job per message, job link and ID, resume link, the blurb, how you know each other, and whether to apply first |
| M10 | Referrals before applying; managers and recruiters after applying |
| M11 | One follow-up after 5 working days that adds one new fact. Then stop |
| W1 | No em or en dashes |
| W2 | No banned word (tailor-resume's list and the user's own) |
| W8 | No hedges or throat-clearing (warning) |
| W10 | Plain text: no bold, bullets, markdown links, curly quotes or emoji |
| FACT | Every number, and every posting skill named, is in `master.tex` (skills may also be in `confirmed-skills.md`) |

What the check cannot see is yours to get right: that each proof sentence really answers one of the top 2 requirements, that the clause about them is true, and that the question is easy.
