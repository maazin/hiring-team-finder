"""Steps 7 and 8 and the tracker: email format, the note gate, outreach.csv."""

import pytest

import email_format as ef
from note_check import check_note, run as run_note, sentences
from outreach import Refused, add, due, mark_bounced, mark_followup, mark_replied, mark_sent, read_rows, write_rows

GOOGLE_MX = lambda domain: ["aspmx.l.google.com."]  # noqa: E731


def site(pages):
    """A fake fetcher: {path: html}. Records every URL asked for."""
    asked = []

    def fetch(url, domain):
        asked.append(url)
        path = "/" + url.split("/", 3)[3] if url.count("/") > 2 else "/"
        return pages.get(path, "")

    fetch.asked = asked
    return fetch


# Five made-up companies whose format is known, and the evidence their pages show.
COMPANIES = [
    ("northwind.example", "first.last", {
        "/team": "<p>Maria Lopez, CTO <a href='mailto:maria.lopez@northwind.example'>email</a></p><p>Ken Adams ken.adams@northwind.example</p>",
        "/contact": "info@northwind.example careers@northwind.example",
    }),
    ("globex.example", "flast", {
        "/about": "Press: Hank Scorpio &lt;hscorpio@globex.example&gt; and Nora Diaz (ndiaz@globex.example)",
        "/privacy": "privacy@globex.example noreply@globex.example",
    }),
    ("initech.example", "first", {
        "/": "Founders Bill Lumbergh bill@initech.example, Peter Gibbons peter@initech.example",
    }),
    ("hooli.example", "firstl", {
        "/press": "Contact Gavin Belson at gavinb@hooli.example or Jack Barker at jackb@hooli.example. press@hooli.example",
    }),
    ("umbrella.example", "first_last", {
        "/contact": "Reach alice_wong@umbrella.example or support@umbrella.example; logo@2x.png",
    }),
]


@pytest.mark.parametrize("domain, pattern, pages", COMPANIES)
def test_best_guess_is_right_on_known_formats(tmp_path, domain, pattern, pages):
    state = ef.get_format(domain, tmp_path, fetch=site(pages), resolve=GOOGLE_MX)
    top = ef.guesses("Jane Doe", state)[0]
    assert top["pattern"] == pattern
    assert top["email"] == ef.local_for(pattern, "jane", "doe") + "@" + domain
    assert state["mx"] == {"receives_mail": True, "provider": "Google", "hosts": ["aspmx.l.google.com"], "error": ""}


def test_labels_follow_the_evidence(tmp_path):
    two = ef.get_format("northwind.example", tmp_path, fetch=site(COMPANIES[0][2]), resolve=GOOGLE_MX)
    labels = [g["label"] for g in ef.guesses("Jane Doe", two)]
    assert labels == ["best", "possible", "possible"]
    one = ef.get_format("umbrella.example", tmp_path, fetch=site(COMPANIES[4][2]), resolve=GOOGLE_MX)
    assert ef.guesses("Jane Doe", one)[0]["label"] == "likely"  # one address read by shape is not enough for best
    none = ef.get_format("empty.example", tmp_path, fetch=site({}), resolve=GOOGLE_MX)
    guesses = ef.guesses("Jane Doe", none)
    assert [g["label"] for g in guesses] == ["possible"] * 3
    assert [g["email"].split("@")[0] for g in guesses] == ["jane.doe", "jane", "jdoe"]  # the common order


def test_role_inboxes_and_junk_are_dropped():
    raw = "info@a.example hr@a.example careers2@a.example noreply@a.example john.doe@a.example real.person@a.example x@other.example"
    assert ef.addresses_in(raw, "a.example") == ["real.person@a.example"]


def test_scan_stays_on_six_pages_and_cache_lasts_90_days(tmp_path, monkeypatch):
    fetch = site(COMPANIES[0][2])
    first = ef.get_format("northwind.example", tmp_path, fetch=fetch, resolve=GOOGLE_MX)
    assert len(fetch.asked) == 6 and {u.rsplit("example", 1)[1] or "/" for u in fetch.asked} == set(ef.PAGES)
    second = ef.get_format("northwind.example", tmp_path, fetch=fetch, resolve=GOOGLE_MX)
    assert first["cached"] is False and second["cached"] is True and len(fetch.asked) == 6
    monkeypatch.setenv("HIRING_TEAM_TODAY", "2027-03-01")  # 105 days later
    assert ef.get_format("northwind.example", tmp_path, fetch=fetch, resolve=GOOGLE_MX)["cached"] is False
    assert len(fetch.asked) == 12


def test_never_fetches_linkedin_or_private_hosts(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("opened a connection")

    monkeypatch.setattr(ef.urllib.request, "build_opener", no_network)
    assert ef.safe_fetch("https://www.linkedin.com/in/someone", "linkedin.com") == ""
    assert ef.safe_fetch("https://evil.example/x", "acme.example") == ""  # not the company's host
    assert ef.safe_fetch("file:///etc/passwd", "acme.example") == ""
    monkeypatch.setattr(ef.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    assert ef.safe_fetch("https://acme.example/", "acme.example") == ""  # resolves to loopback
    monkeypatch.setattr(ef.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
    assert ef.safe_fetch("https://intranet.acme.example/", "acme.example") == ""
    with pytest.raises(ValueError):
        ef.get_format("linkedin.com", "/tmp/unused")


def test_no_mx_and_lookup_failure(tmp_path):
    assert ef.mx_lookup("x.example", lambda d: [])["receives_mail"] is False
    assert ef.mx_lookup("x.example", lambda d: ["x-example.mail.protection.outlook.com"])["provider"] == "Microsoft"

    def broken(domain):
        raise TimeoutError("no network")

    out = ef.mx_lookup("x.example", broken)
    assert out["receives_mail"] is None and "no network" in out["error"]


def test_learning_and_bounces_change_the_next_guess(tmp_path):
    state = ef.get_format("empty.example", tmp_path, fetch=site({}), resolve=GOOGLE_MX)
    assert ef.guesses("Jane Doe", state)[0]["email"] == "jane.doe@empty.example"
    state = ef.learn("empty.example", "Raj Patel", "rpatel@empty.example", tmp_path)
    top = ef.guesses("Jane Doe", state)[0]
    assert (top["email"], top["label"]) == ("jdoe@empty.example", "best")  # a confirmed address is enough
    state = ef.record_bounce("empty.example", "Jane Doe", "jdoe@empty.example", tmp_path, "best")
    emails = [g["email"] for g in ef.guesses("Jane Doe", state)]
    assert "jdoe@empty.example" not in emails
    assert state["patterns"][0]["confidence"] == 0.5  # the best-guess bounce halved it
    with pytest.raises(ValueError):
        ef.learn("empty.example", "Info", "info@empty.example", tmp_path)
    # confirmed addresses outlive a refresh
    assert ef.get_format("empty.example", tmp_path, refresh=True, fetch=site({}), resolve=GOOGLE_MX)["confirmed"]


def test_names():
    assert ef.split_name("Dr. María de la Cruz, PhD") == ("maria", "delacruz")
    assert ef.split_name("Jean-Luc O'Neil Jr.") == ("jeanluc", "oneil")
    assert ef.split_name("Jane Q. Doe") == ("jane", "doe")
    assert ef.guesses("Cher", {"domain": "a.example"}) == []
    assert 25 <= len(ef.PATTERNS) <= 35
    assert len({fn("jane", "doe") for fn in ef.PATTERNS.values()}) == len(ef.PATTERNS)


# ---- notes ----

JOB_URL = "https://boards.greenhouse.io/exampleco/jobs/4000001"
RESUME_URL = "https://example.org/r/jordan-rivera-example-co.pdf"

MANAGER = {
    "kind": "manager", "to_name": "Jane Doe", "subject": "Data Engineer, R-4471", "greeting": "Hi Jane,",
    "body": (
        "I applied for the Data Engineer, New Grad, Data Platform role (R-4471) on your Data Platform team. "
        "At Northwind Freight I built 12 Airflow pipelines in Python that load 40M rows a day into PostgreSQL. "
        "I also cut a nightly SQL job from 90 minutes to 14 by rewriting 6 joins as window functions. "
        f"My resume is here: {RESUME_URL} and the posting is here: {JOB_URL}. "
        "Is the team still hiring for this role?"
    ),
    "signoff": "Thanks,\nJordan Rivera", "applied": True, "job_url": JOB_URL, "resume_url": RESUME_URL,
    "knows_them": "on your Data Platform team", "attachments": [],
}
RECRUITER = {
    "kind": "recruiter", "to_name": "Rita Park", "subject": "Data Engineer, R-4471", "greeting": "Hi Rita,",
    "body": (
        "I applied for the Data Engineer, New Grad, Data Platform role (R-4471). "
        "At Northwind Freight I built 12 Airflow pipelines in Python that load 40M rows a day. "
        "I also cut a nightly SQL job from 90 minutes to 14. "
        f"My resume is here: {RESUME_URL}. "
        "If you are not the recruiter for this role, who should I contact?"
    ),
    "signoff": "Thanks,\nJordan Rivera", "applied": True, "job_url": JOB_URL, "resume_url": RESUME_URL,
    "knows_them": "", "attachments": [],
}
REFERRAL = {
    "kind": "referral", "to_name": "Priya Raman", "subject": "Example Co referral", "greeting": "Hi Priya,",
    "body": (
        "We met at the Data Science Club pipeline workshop in March. "
        f"I plan to apply for the Data Engineer, New Grad, Data Platform role (R-4471) at Example Co: {JOB_URL}. "
        f"My resume for it is here: {RESUME_URL}. "
        "Would you rather I apply first, or go through your referral form? A short blurb is below in case it helps."
    ),
    "blurb": (
        "Jordan built 12 Airflow pipelines in Python at Northwind Freight that load 40M rows a day. "
        "He also cut a nightly SQL job from 90 minutes to 14. We know each other from the Data Science Club."
    ),
    "signoff": "Thanks,\nJordan", "applied": False, "job_url": JOB_URL, "resume_url": RESUME_URL,
    "how_we_know": "We met at the Data Science Club pipeline workshop", "attachments": [],
}
LINKEDIN = {
    "kind": "linkedin", "to_name": "Jane Doe",
    "body": "I applied for the Data Engineer, New Grad, Data Platform role (R-4471). At Northwind Freight I built 12 Airflow pipelines loading 40M rows a day.",
}
FOLLOWUP = {
    "kind": "followup", "to_name": "Jane Doe", "subject": "Data Engineer, R-4471", "greeting": "Hi Jane,",
    "body": "Since my note about the Data Engineer role, I wrote 35 data quality tests that caught 9 bad loads before they reached billing. Is the role still open?",
    "signoff": "Thanks,\nJordan Rivera", "new_fact": "I wrote 35 data quality tests that caught 9 bad loads",
}


def rules(note, job, posting, master_tex, severity="block", **kwargs):
    return sorted({f.rule for f in check_note(note, job, posting, master_tex, **kwargs) if f.severity == severity})


@pytest.mark.parametrize("note, low, high", [(MANAGER, 50, 100), (RECRUITER, 50, 80), (REFERRAL, 30, 99), (FOLLOWUP, 15, 60)])
def test_templates_pass_and_stay_inside_their_word_limits(note, low, high, job, posting, master_tex):
    result = run_note(note, job, posting, master_tex, banned=["leverage", "seamless"])
    assert result["blocking"] == [] and result["passed"]
    assert low <= result["words"] <= high


def test_linkedin_note_fits_200_characters(job, posting, master_tex):
    result = run_note(LINKEDIN, job, posting, master_tex)
    assert result["passed"] and result["characters"] <= 200
    assert rules({**LINKEDIN, "body": LINKEDIN["body"] + " Could we connect and talk about the team and the role sometime soon?"}, job, posting, master_tex) == ["M7"]


PLANTED = [
    ("M1", {"body": "Hello, I am a recent graduate. " + MANAGER["body"]}),
    ("M1", {"body": MANAGER["body"].replace("(R-4471) ", "")}),
    ("M2", {"body": MANAGER["body"].replace("12 Airflow", "many Airflow").replace("40M rows", "lots of rows").replace("from 90 minutes to 14 by rewriting 6 joins", "by rewriting joins")}),
    ("FACT", {"body": MANAGER["body"].replace("40M rows", "75M rows")}),
    ("FACT", {"body": MANAGER["body"].replace("in Python that", "in Python on Kubernetes that")}),
    ("M3", {"body": MANAGER["body"].replace("I also cut", "I am passionate and also cut")}),
    ("M4", {"knows_them": ""}),
    ("M4", {"knows_them": "your talk at DataConf"}),
    ("M5", {"body": MANAGER["body"] + " Could you also share the team's roadmap?"}),
    ("M5", {"body": MANAGER["body"].replace("Is the team still hiring for this role?", "Could you spare 30 minutes this week?")}),
    ("M6", {"body": MANAGER["body"] + " " + "I would add much more detail here about every project. " * 3}),
    ("M6", {"subject": "Application for the Data Engineer role"}),
    ("M8", {"attachments": ["resume.pdf"]}),
    ("M8", {"body": MANAGER["body"].replace("My resume is here", "My resume is attached and also here")}),
    ("M8", {"resume_url": ""}),
    ("M10", {"applied": False}),
    ("W1", {"body": MANAGER["body"].replace("team. At", "team — at")}),
    ("W2", {"body": MANAGER["body"].replace("I built", "I leveraged")}),
    ("W10", {"body": MANAGER["body"].replace("12 Airflow pipelines", "**12 Airflow pipelines**")}),
]


@pytest.mark.parametrize("rule, change", PLANTED)
def test_planted_violations_block(rule, change, job, posting, master_tex):
    found = rules({**MANAGER, **change}, job, posting, master_tex, banned=["leverage"])
    assert rule in found, found


def test_confirmed_skill_may_be_named(job, posting, master_tex):
    note = {**MANAGER, "body": MANAGER["body"].replace("in Python that", "in Python on Kubernetes that")}
    assert "FACT" not in rules(note, job, posting, master_tex, confirmed=["Kubernetes"])


def test_referral_and_followup_rules(job, posting, master_tex):
    assert rules({**REFERRAL, "blurb": "One sentence only."}, job, posting, master_tex) == ["M9"]
    assert rules({**REFERRAL, "body": REFERRAL["body"].replace(JOB_URL, "the careers page")}, job, posting, master_tex) == ["M9"]
    assert rules({**REFERRAL, "how_we_know": ""}, job, posting, master_tex) == ["M4"]
    assert rules({**REFERRAL, "applied": True}, job, posting, master_tex, severity="warn") == ["M10"]
    assert rules({**FOLLOWUP, "new_fact": ""}, job, posting, master_tex) == ["M11"]
    assert rules({**FOLLOWUP, "body": "Just following up on my note about the Data Engineer role from last week. Is the role still open?"}, job, posting, master_tex) == ["M11"]


def test_unreadable_job_id_needs_the_link(job, master_tex):
    posting = {"job_id": "1b2c3d4e-0000-1111-2222-333344445555", "job_id_kind": "uuid"}
    body = MANAGER["body"].replace(" (R-4471)", "")
    assert run_note({**MANAGER, "body": body}, job, posting, master_tex)["passed"]
    assert "M1" in rules({**MANAGER, "body": body.replace(f" and the posting is here: {JOB_URL}", "")}, job, posting, master_tex)


def test_sentence_split_keeps_abbreviations_and_links():
    assert len(sentences("I applied for the Sr. Data Engineer role. See https://a.example/x.pdf now. Thanks!")) == 3


# ---- outreach ----


def base(**extra):
    return dict(company="Example Co", job_id="R-4471", job_url=JOB_URL, title="T", slot="manager", profile_url="https://www.linkedin.com/in/x", path="cold", **extra)


def test_sent_sets_follow_up_five_working_days_later(tmp_path):
    rows = []
    add(rows, name="Jane Doe", email="jane.doe@empty.example", email_confidence="possible", **base())
    assert rows[0]["status"] == "drafted"
    row = mark_sent(rows, "Example Co", "R-4471", "Jane Doe")
    assert (row["sent_on"], row["follow_up_on"]) == ("2026-11-16", "2026-11-23")  # Monday to the next Monday
    import datetime as dt

    assert mark_sent(rows, "Example Co", "R-4471", "Jane Doe", dt.date(2026, 11, 19))["follow_up_on"] == "2026-11-26"
    path = tmp_path / "lab" / "outreach.csv"
    write_rows(path, rows)
    assert read_rows(path) == rows


def test_caps_three_people_two_waiting_and_do_not_contact():
    rows = []
    for name in ("A One", "B Two", "C Three"):
        add(rows, name=name, **base())
    with pytest.raises(Refused, match="cap per posting"):
        add(rows, name="D Four", **base())
    add(rows, name="D Four", **{**base(), "job_id": "R-9999"})  # another posting is fine
    mark_sent(rows, "Example Co", "R-4471", "A One")
    mark_sent(rows, "Example Co", "R-4471", "B Two")
    with pytest.raises(Refused, match="1 or 2 people at a time"):
        mark_sent(rows, "Example Co", "R-4471", "C Three")
    from outreach import mark_dnc

    mark_dnc(rows, "Example Co", "R-9999", "D Four")
    with pytest.raises(Refused, match="do-not-contact"):
        add(rows, name="D Four", **{**base(), "company": "Globex", "job_id": "G-1"})


def test_planted_reply_closes_the_row_and_teaches_the_format(tmp_path):
    rows = []
    add(rows, name="Jane Doe", email="jane.doe@empty.example", email_confidence="possible", **base())
    mark_sent(rows, "Example Co", "R-4471", "Jane Doe")
    import datetime as dt

    assert due(rows, dt.date(2026, 11, 20)) == []
    assert [r["name"] for r in due(rows, dt.date(2026, 11, 23))] == ["Jane Doe"]
    out = mark_replied(rows, "Example Co", "R-4471", "Jane Doe", "jdoe@empty.example", cache_dir=tmp_path)
    assert out["row"]["status"] == "replied" and out["learned_format"]
    assert due(rows, dt.date(2026, 12, 1)) == []
    state = ef.get_format("empty.example", tmp_path, scan=False, resolve=GOOGLE_MX)
    assert ef.guesses("Raj Patel", state)[0]["email"] == "rpatel@empty.example"
    with pytest.raises(Refused, match="not waiting"):
        mark_followup(rows, "Example Co", "R-4471", "Jane Doe")


def test_planted_bounce_moves_to_the_next_guess(tmp_path):
    ef.get_format("empty.example", tmp_path, fetch=site({}), resolve=GOOGLE_MX)
    rows = []
    add(rows, name="Jane Doe", email="jane.doe@empty.example", email_confidence="possible", **base())
    mark_sent(rows, "Example Co", "R-4471", "Jane Doe")
    out = mark_bounced(rows, "Example Co", "R-4471", "Jane Doe", cache_dir=tmp_path)
    assert out["redraft"] and out["wrong"] == "jane.doe@empty.example"
    row = out["row"]
    assert (row["email"], row["status"], row["sent_on"]) == ("jane@empty.example", "drafted", "")
    assert row["bounced_emails"] == "jane.doe@empty.example"
    mark_sent(rows, "Example Co", "R-4471", "Jane Doe")
    assert mark_bounced(rows, "Example Co", "R-4471", "Jane Doe", cache_dir=tmp_path)["row"]["email"] == "jdoe@empty.example"
    mark_sent(rows, "Example Co", "R-4471", "Jane Doe")
    last = mark_bounced(rows, "Example Co", "R-4471", "Jane Doe", cache_dir=tmp_path)  # the third guess fails too
    assert last["redraft"] is False and last["row"]["status"] == "bounced"


def test_one_follow_up_then_stop():
    rows = []
    add(rows, name="Jane Doe", **base())
    mark_sent(rows, "Example Co", "R-4471", "Jane Doe")
    row = mark_followup(rows, "Example Co", "R-4471", "Jane Doe")
    assert row["status"] == "no reply" and row["follow_up_sent_on"] == "2026-11-16"
    with pytest.raises(Refused, match="one follow-up"):
        mark_followup(rows, "Example Co", "R-4471", "Jane Doe")
