"""Step 7 gate: a note is saved as a Gmail draft only after this passes (G8).

Checks one note.json against the message rules M1 to M11, the writing rules
that apply to a short note (W1 dashes, W2 banned words, W8 hedges, W10 plain
formatting) and a fact gate: every number in the note, and every posting
skill it names, must be in master.tex (or confirmed-skills.md for skills).

  M1  the first sentence names the exact job title and job ID
  M2  two sentences each carry a real result (a number from the master resume)
  M3  no filler self-description (passionate, results-driven, ...)
  M4  one clause shows you know who they are; never their personal life
  M5  one question, answerable in a line; never "review my resume" or "30 minutes"
  M6  email body 50 to 100 words (recruiter 50 to 80); subject 4 words or fewer
  M7  LinkedIn connection note: 200 characters or fewer, M1 and one proof point, no ask
  M8  no attachment; link the tailored resume
  M9  referral: one job, job link and ID, resume link, a 2 to 3 sentence blurb,
      how you know each other, and whether they prefer you apply first
  M10 referrals before applying; managers and recruiters after applying
  M11 one follow-up that adds one new fact

note.json:
  {"kind": "manager|recruiter|referral|linkedin|followup", "to_name": "", "subject": "",
   "greeting": "Hi Jane,", "body": "", "signoff": "", "applied": true,
   "job_url": "", "resume_url": "", "knows_them": "clause copied from the body",
   "how_we_know": "referral: clause copied from the body", "blurb": "referral: paste-ready blurb",
   "new_fact": "followup: clause copied from the body", "attachments": []}

CLI:
  note_check.py --note note.json --job job.json --posting posting.json --master master.tex
                [--confirmed confirmed-skills.md] [--banned banned-words.txt]...
Exit code 1 when any rule blocks. Do not create the draft then; fix the note and run again.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from shared import Finding, dump_json, find_tailor_resume, load_json

KINDS = ("manager", "recruiter", "referral", "linkedin", "followup")
WORD_LIMITS = {"manager": (50, 100), "recruiter": (50, 80), "referral": (30, 99), "followup": (15, 60)}
LINKEDIN_CHARS = 200
SUBJECT_WORDS = 4

FILLER = (
    "passionate", "results-driven", "results driven", "hardworking", "hard-working", "hard working", "team player",
    "go-getter", "go getter", "eager to learn", "self-starter", "self starter", "detail-oriented", "detail oriented",
    "highly motivated", "fast learner", "quick learner", "think outside the box",
)
BAD_ASKS = (
    r"review (?:of )?my resume", r"look (?:at|over) my resume",
    # their time, not a result such as "from 90 minutes to 14"
    r"\b\d+\s*(?:minutes|mins?)\s+(?:of your time|to (?:chat|talk|connect|meet)|(?:this|next) week|call|chat)",
    r"\b(?:spare|have|got)\s+(?:\d+|a few|a couple of)\s*(?:minutes|mins?)\b", r"half an hour",
    r"pick your brain", r"hop on a call", r"jump on a call", r"quick call", r"coffee chat", r"refer me\?",
)
HEDGES = (
    "i think", "i believe", "i feel", "just wanted", "i was wondering", "hopefully", "kind of", "sort of", "perhaps",
    "maybe", "i hope this finds you well", "hope you are doing well", "hope you're doing well", "sorry to bother",
)
PERSONAL = (
    "your family", "your wife", "your husband", "your kids", "your children", "your vacation", "your wedding",
    "your birthday", "your girlfriend", "your boyfriend", "your baby", "your house", "your instagram", "your facebook",
)
FOLLOWUP_FILLER = ("just following up", "circling back", "bumping this", "bump this", "checking in again", "any update")

_ABBREVIATIONS = ("Sr.", "Jr.", "Inc.", "Co.", "Dr.", "Mr.", "Ms.", "Mrs.", "St.", "vs.", "e.g.", "i.e.", "U.S.", "No.")
_URL = re.compile(r"https?://\S+")
_NUMBER = re.compile(r"(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)\s?(%|[kKmMbB]\b|\+)?")
_MULTIPLIER = {"k": 1e3, "m": 1e6, "b": 1e9}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27}$", re.IGNORECASE)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
_MARKUP = re.compile(r"\*\*|__|(?<!\w)\*\w[^*\n]*\*(?!\w)|\[[^\]]+\]\([^)]+\)|^\s*[-*\u2022]\s", re.MULTILINE)


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------


def sentences(text: str) -> list[str]:
    protected = text or ""
    for abbreviation in _ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation.replace(".", "\x00"))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])|\n{2,}", protected.strip())
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def word_count(text: str) -> int:
    return len((text or "").split())


def has_term(term: str, text: str) -> bool:
    return bool(term) and re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def number_values(text: str) -> set[float]:
    values: set[float] = set()
    for match in _NUMBER.finditer(text or ""):
        try:
            value = float(match.group(1).replace(",", "").rstrip("."))
        except ValueError:
            continue
        values.add(value * _MULTIPLIER.get((match.group(2) or "").lower(), 1.0))
        values.add(value)  # "40k" in the note also matches a bare 40 next to "k" in the master
    return values


def numbers_with_text(text: str) -> list[tuple[str, float]]:
    found = []
    for match in _NUMBER.finditer(text or ""):
        try:
            value = float(match.group(1).replace(",", "").rstrip("."))
        except ValueError:
            continue
        found.append((match.group(0).strip(), value * _MULTIPLIER.get((match.group(2) or "").lower(), 1.0)))
    return found


def detex(tex: str) -> str:
    """Plain enough text from master.tex for number and term lookups."""
    text = re.sub(r"(?<!\\)%.*", "", tex or "")
    for escaped, plain in ((r"\%", "%"), (r"\$", "$"), (r"\&", "&"), (r"\#", "#"), (r"\_", "_"), ("{,}", ","), ("~", " ")):
        text = text.replace(escaped, plain)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    return re.sub(r"\s+", " ", text.replace("{", " ").replace("}", " ").replace("$", " $"))


def read_words(paths: list[str | Path]) -> list[str]:
    words: list[str] = []
    for path in paths:
        if path and Path(path).is_file():
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line and line.lower() not in words:
                    words.append(line.lower())
    return words


def banned_pattern(entry: str) -> re.Pattern[str]:
    """A single word matches in every form (leverage, leveraged, leveraging); a phrase as written."""
    if " " in entry or "-" in entry:
        return re.compile(r"(?<![A-Za-z])" + re.escape(entry).replace(r"\ ", r"[\s-]+") + r"(?![A-Za-z])", re.IGNORECASE)
    stem = entry[:-1] if entry.endswith("e") and len(entry) > 3 else entry
    return re.compile(r"(?<![A-Za-z])" + re.escape(stem) + r"(?:e|es|ed|d|ing|s|ly)?(?![A-Za-z])", re.IGNORECASE)


def clean_title(title: str) -> str:
    cleaned = re.sub(r"\s*[-(,]?\s*\b(?:Req(?:uisition)?|Job ID|R-?\d|JR)\b.*$", "", title or "", flags=re.IGNORECASE)
    return re.sub(r"\s*\([^)]*\)\s*", " ", cleaned).strip(" -,")


def default_banned_files() -> list[Path]:
    tailor = find_tailor_resume()
    return [tailor / "references" / "banned-words.txt"] if tailor else []


# --------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------


def check_note(
    note: dict[str, Any], job: dict[str, Any], posting: dict[str, Any] | None = None, master_tex: str = "",
    confirmed: list[str] | None = None, banned: list[str] | None = None,
) -> list[Finding]:
    posting = posting or {}
    out: list[Finding] = []

    def block(rule: str, message: str, value: str = "") -> None:
        out.append(Finding(rule, "block", message, "note", value))

    def warn(rule: str, message: str, value: str = "") -> None:
        out.append(Finding(rule, "warn", message, "note", value))

    kind = str(note.get("kind") or "")
    if kind not in KINDS:
        block("NOTE", f"kind must be one of {', '.join(KINDS)}", kind)
        return out
    body = str(note.get("body") or "").strip()
    subject = str(note.get("subject") or "").strip()
    blurb = str(note.get("blurb") or "").strip()
    everything = "\n".join(x for x in (subject, str(note.get("greeting") or ""), body, blurb, str(note.get("signoff") or "")) if x)
    low = everything.lower()
    job_url, resume_url = str(note.get("job_url") or ""), str(note.get("resume_url") or "")
    title, job_id = str(job.get("title") or ""), str(posting.get("job_id") or "")
    readable_id = bool(job_id) and posting.get("job_id_kind") != "uuid" and not _UUID.match(job_id)
    email_kind = kind in ("manager", "recruiter", "referral", "followup")
    if not body:
        block("NOTE", "the note has no body")
        return out

    # M1 / M7: the exact job in the first sentence.
    first = sentences(body)[0]
    titles = [t for t in {title, clean_title(title)} if t]
    title_ok = lambda text: any(t.lower() in text.lower() for t in titles)  # noqa: E731
    if kind in ("manager", "recruiter", "linkedin"):
        if not title_ok(first):
            block("M1", f"the first sentence must name the exact job title: {clean_title(title) or title}", first)
        if readable_id and job_id.lower() not in first.lower():
            block("M1", f"the first sentence must name the job ID: {job_id}", first)
        if not job_id:
            block("M1", "no job ID is known; ask the user for it and add it to posting.json")
        elif not readable_id and kind != "linkedin" and (not job_url or job_url not in body):
            block("M1", "this posting's ID is an unreadable link id; put the job link in the note instead")

    # Fact gate: numbers and posting skills must come from the master resume.
    master_text = detex(master_tex)
    master_numbers = number_values(master_text)
    masked = _URL.sub(" ", body + "\n" + blurb)
    for hide in [job_id, *titles]:
        if hide:
            masked = re.sub(re.escape(hide), " ", masked, flags=re.IGNORECASE)
    supported_any = False
    for shown, value in numbers_with_text(masked):
        if value in master_numbers:
            supported_any = True
        else:
            block("FACT", "this number is not in master.tex; use a real result or remove it", shown)
    requirements = job.get("requirements") or {}
    skills = [str(s) for s in (requirements.get("required_skills") or []) + (requirements.get("preferred_skills") or [])]
    confirmed_low = [c.lower() for c in confirmed or []]
    for skill in dict.fromkeys(skills):
        if has_term(skill, masked) and not has_term(skill, master_text) and skill.lower() not in confirmed_low:
            block("FACT", "the note claims a posting skill that is not in master.tex or confirmed-skills.md", skill)

    # M2: proof points.
    def proves(sentence: str) -> bool:
        for hide in [job_id, *titles]:
            if hide:
                sentence = re.sub(re.escape(hide), " ", sentence, flags=re.IGNORECASE)
        return any(value in master_numbers for _, value in numbers_with_text(sentence))

    proof = [s for s in sentences(_URL.sub(" ", body)) if proves(s)]
    needed = {"manager": 2, "recruiter": 2, "linkedin": 1}.get(kind, 0)
    if len(proof) < needed:
        block("M2", f"needs {needed} sentence(s) that each prove a requirement with a real number from the master resume; found {len(proof)}")
    if needed == 2:
        named = [s for s in (requirements.get("required_skills") or []) if has_term(str(s), body)]
        if requirements.get("required_skills") and len(named) < 2:
            warn("M2", "the proof points name fewer than 2 of the posting's required skills; match them to its top 2 requirements", ", ".join(map(str, named)))
    if kind == "referral" and blurb and not supported_any:
        warn("M2", "the referral blurb has no real result with a number")

    # M3, W2: filler and banned words.
    for phrase in FILLER:
        if banned_pattern(phrase).search(everything):
            block("M3", "filler self-description; show the result instead", phrase)
    for entry in banned or []:
        if entry not in FILLER and banned_pattern(entry).search(everything):
            block("W2", "banned word or phrase", entry)

    # M4: who they are.
    clause = str(note.get("how_we_know" if kind == "referral" else "knows_them") or "").strip()
    if kind in ("manager", "referral"):
        if not clause:
            block("M4", "name the clause that shows you know who they are" + (" (how_we_know)" if kind == "referral" else " (knows_them): their team, a post or talk, or how you are connected"))
        elif clause.lower() not in body.lower():
            block("M4", "that clause is not in the body", clause)
    elif kind == "recruiter" and not clause:
        warn("M4", "no clause shows you know who they are; one on the level or team they recruit for helps")
    for phrase in PERSONAL:
        if phrase in low:
            block("M4", "never mention their personal life", phrase)

    # M5: one easy question.
    questions = body.count("?")
    if kind in ("manager", "recruiter", "referral") and questions != 1:
        block("M5", f"exactly one question, answerable in a line; found {questions}")
    if kind == "followup" and questions > 1:
        block("M5", f"at most one question in a follow-up; found {questions}")
    if kind == "linkedin" and questions:
        block("M7", "a connection note makes no ask beyond connecting; remove the question")
    for pattern in BAD_ASKS:
        match = re.search(pattern, low)
        if match:
            block("M5", "not in a first note: no resume reviews, calls or blocks of their time", match.group(0))

    # M6, M7: length.
    if kind == "linkedin":
        if len(body) > LINKEDIN_CHARS:
            block("M7", f"{len(body)} characters; LinkedIn caps a connection note at {LINKEDIN_CHARS}")
    else:
        low_limit, high_limit = WORD_LIMITS[kind]
        count = word_count(body)
        if not low_limit <= count <= high_limit:
            block("M6" if kind != "followup" else "M11", f"body is {count} words; a {kind} note is {low_limit} to {high_limit}")
        if not subject:
            block("M6", "an email needs a subject line of 4 words or fewer, such as \"Data Engineer, R-4471\"")
        elif word_count(subject) > SUBJECT_WORDS:
            block("M6", f"subject is {word_count(subject)} words; 4 or fewer", subject)

    # M8: link, never attach.
    if email_kind:
        if note.get("attachments"):
            block("M8", "no attachments; link the tailored resume instead")
        match = re.search(r"\battach(?:ed|ing|ment)?\b|\benclosed\b", low)
        if match:
            block("M8", "the note talks about an attachment; link the tailored resume instead", match.group(0))
        if kind != "followup" and (not resume_url or resume_url not in body):
            block("M8", "link the tailored resume in the body (resume_url)")
        if kind in ("manager", "recruiter") and readable_id and (not job_url or job_url not in body):
            warn("M8", "the job link is not in the body")

    # M9: referral asks.
    if kind == "referral":
        if not job_url or job_url not in body:
            block("M9", "a referral ask carries the job link")
        if not title_ok(body):
            block("M9", f"name the job title: {clean_title(title) or title}")
        if readable_id and job_id.lower() not in body.lower():
            block("M9", f"name the job ID: {job_id}")
        blurb_sentences = len(sentences(blurb))
        if not 2 <= blurb_sentences <= 3:
            block("M9", f"the paste-ready blurb is 2 to 3 sentences; found {blurb_sentences}")
        if not re.search(r"\bappl(?:y|ied|ying)\b", body, re.IGNORECASE):
            block("M9", "ask whether they prefer you apply first")
        if len(set(_URL.findall(body))) > 2:
            block("M9", "one job per message: only the job link and the resume link")
        if re.match(r"\s*(?:will|would|could|can) you refer me", body, re.IGNORECASE):
            block("M9", "do not open with \"will you refer me\"")

    # M10: timing.
    applied = note.get("applied")
    if kind in ("manager", "recruiter") and applied is not True:
        block("M10", "message managers and recruiters after applying; apply first, then set applied to true")
    if kind == "referral" and applied is True:
        warn("M10", "referral asks work best before applying; say in the note that you already applied")

    # M11: the one follow-up.
    if kind == "followup":
        new_fact = str(note.get("new_fact") or "").strip()
        if not new_fact:
            block("M11", "a follow-up adds one new fact (new_fact): a shipped project or a new result")
        elif new_fact.lower() not in body.lower():
            block("M11", "the new fact is not in the body", new_fact)
        for phrase in FOLLOWUP_FILLER:
            if phrase in low:
                block("M11", "the follow-up must add something, not only nudge", phrase)

    # W1, W8, W10.
    if "\u2014" in everything or "\u2013" in everything:
        block("W1", "no em or en dashes; use a comma, a full stop or \"to\"")
    if _MARKUP.search(body) or _EMOJI.search(everything) or re.search("[\u2018\u2019\u201C\u201D]", everything):
        block("W10", "plain text only: no bold, bullets, markdown links, curly quotes or emoji")
    for phrase in HEDGES:
        if phrase in low:
            warn("W8", "hedge or throat-clearing; say it directly", phrase)
    return out


def run(
    note: dict[str, Any], job: dict[str, Any], posting: dict[str, Any] | None, master_tex: str,
    confirmed: list[str] | None = None, banned: list[str] | None = None,
) -> dict[str, Any]:
    findings = check_note(note, job, posting, master_tex, confirmed, banned)
    body = str(note.get("body") or "")
    return {
        "kind": note.get("kind", ""),
        "passed": not any(f.severity == "block" for f in findings),
        "words": word_count(body),
        "characters": len(body.strip()),
        "blocking": [f.to_dict() for f in findings if f.severity == "block"],
        "warnings": [f.to_dict() for f in findings if f.severity == "warn"],
    }


def read_confirmed(path: str | Path | None) -> list[str]:
    if not path or not Path(path).is_file():
        return []
    skills = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*[-*]\s+(.*)", line)
        if match:
            skills.append(match.group(1).split("|", 1)[0].strip().strip("`*"))
    return [s for s in skills if s]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Message rules M1 to M11, writing rules and the fact gate for one note")
    parser.add_argument("--note", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--posting")
    parser.add_argument("--master", required=True)
    parser.add_argument("--confirmed")
    parser.add_argument("--banned", action="append", default=[])
    args = parser.parse_args(argv)
    posting = load_json(args.posting) if args.posting and Path(args.posting).is_file() else {}
    banned = read_words([*default_banned_files(), *args.banned])
    result = run(
        load_json(args.note), load_json(args.job), posting, Path(args.master).read_text(encoding="utf-8"),
        read_confirmed(args.confirmed), banned,
    )
    print(dump_json(result), end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
