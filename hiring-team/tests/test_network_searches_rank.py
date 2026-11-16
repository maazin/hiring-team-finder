"""Steps 3, 4 and 6: the network match, the 6 searches and the ranking."""

from urllib.parse import urlparse

import pytest

from conftest import FIXTURES
from network import alumni_link, load_profile, read_connections, run
from rank import rank, report, score
from searches import MAX_SEARCHES, ORDER, hand_search, log_search, render
from shared import normalize_company

CONNECTIONS = FIXTURES / "Connections.csv"
CONTACTS = FIXTURES / "contacts.csv"


def names(result):
    return [p["name"] for p in result["people"]]


def test_reads_linkedin_export_with_notes_preamble():
    rows = read_connections(CONNECTIONS)
    assert len(rows) == 8 and rows[0]["name"] == "Priya Raman" and rows[0]["company"] == "Example Co, Inc."


@pytest.mark.parametrize("company, expected", [
    ("Example Co", {"Priya Raman", "Marcus Lee", "Sofia Mendez"}),  # "Example Co, Inc." normalises
    ("Google", {"Dana Ortiz", "Lena Fischer"}),  # brand (YouTube) and "Google Cloud"
    ("Alphabet", {"Dana Ortiz", "Lena Fischer"}),  # parent
    ("Amazon", {"Sam Okafor"}),  # "Amazon Web Services (AWS)"
    ("Meta", {"Ines Cruz"}),  # Instagram
    ("Salesforce", {"Raj Patel", "Omar Haddad"}),  # Slack, plus a club contact
])
def test_finds_known_connections(company, expected):
    result = run(company, "software_engineering", CONNECTIONS, CONTACTS)
    assert set(names(result)) == expected


def test_x_does_not_match_xerox():
    assert names(run("X", "software_engineering", CONNECTIONS, None)) == []


def test_same_function_ranks_first_and_direct_beats_club():
    result = run("Example Co", "data_engineering", CONNECTIONS, CONTACTS)
    assert names(result)[0] == "Priya Raman"
    priya = result["people"][0]
    assert priya["warmth"] == "direct" and priya["closeness"] == "peer" and priya["path"] == "direct connection"
    sofia = next(p for p in result["people"] if p["name"] == "Sofia Mendez")
    assert sofia["warmth"] == "club" and sofia["path"] == "SHPE"
    marcus = next(p for p in result["people"] if p["name"] == "Marcus Lee")
    assert marcus["closeness"] == "none"
    assert "university-of-south-florida" in result["alumni_page"] and "Example+Co" in result["alumni_page"]


def test_second_run_reuses_the_cache(tmp_path):
    out = tmp_path / "network.json"
    first = run("Example Co", "data_engineering", CONNECTIONS, CONTACTS, output=out)
    second = run("Example Co", "data_engineering", CONNECTIONS, CONTACTS, output=out)
    assert first["cached"] is False and second["cached"] is True and names(first) == names(second)
    assert run("Example Co", "data_engineering", CONNECTIONS, CONTACTS, output=out, refresh=True)["cached"] is False


def test_missing_export_says_how_to_get_it(tmp_path):
    result = run("Example Co", "data_engineering", tmp_path / "nope.csv")
    assert result["people"] == [] and "Get a copy of your data" in result["missing"][0]


def test_normalize_company():
    assert normalize_company("Acme, Inc.") == "acme"
    assert normalize_company("AT&T") == "at and t"
    assert alumni_link("Acme", load_profile(None)).startswith("https://www.linkedin.com/school/")


# ---- searches ----


def test_six_templates_match_the_prd(targets):
    searches = render(targets)
    assert [s["id"] for s in searches] == list(ORDER) and len(searches) == MAX_SEARCHES
    q = {s["id"]: s["query"] for s in searches}
    assert q["manager"] == 'site:linkedin.com/in "Example Co" ("Engineering Manager" OR "Data Engineering Manager") "Data Platform"'
    assert q["hiring"] == 'site:linkedin.com/in "Example Co" inanchor:hiring "data" -recruiter'
    assert q["recruiter"] == 'site:linkedin.com/in "Example Co" ("University Recruiter" OR "Early Career Recruiter" OR "Technical Recruiter")'
    assert q["new_hires"] == 'site:linkedin.com/posts "Example Co" ("excited to join" OR "accepted an offer") recruiter'
    assert q["alumni"] == 'site:linkedin.com/in "Example Co" "Data Engineer" ("University of South Florida" OR "SHPE")'
    assert q["team"] == '"Example Co" "Data Platform" (engineering blog OR talk OR podcast)'


def test_every_output_is_a_plain_search_link(targets):
    for search in render(targets):
        for link in search["links"].values():
            host = urlparse(link).hostname
            assert host in ("www.google.com", "www.bing.com", "duckduckgo.com")
            assert "linkedin.com" not in host


def test_ledger_refuses_repeats_and_a_seventh(tmp_path):
    for search_id in ORDER:
        assert log_search(tmp_path, search_id)[0]
    ok, message = log_search(tmp_path, "manager")
    assert not ok and "already ran" in message
    assert not log_search(tmp_path, "made_up")[0]
    (tmp_path / "searches_run.json").write_text('["a","b","c","d","e","f"]')
    ok, message = log_search(tmp_path, "team")
    assert not ok and "6 searches" in message


def test_unknown_team_is_left_out_of_queries():
    from targets import build_targets

    q = {s["id"]: s["query"] for s in render(build_targets({"company": "Acme", "title": "Software Engineer", "description_text": ""}))}
    assert "unknown" not in q["manager"] and q["team"] == '"Acme" "engineering" (engineering blog OR talk OR podcast)'


# ---- ranking ----


def person(name, slot, warmth, closeness, evidence, **extra):
    return {
        "name": name, "title": "T", "company": "Example Co", "slot": slot, "warmth": warmth, "closeness": closeness,
        "evidence": evidence, "profile_url": f"https://www.linkedin.com/in/{name.lower().replace(' ', '-')}", **extra,
    }


def test_direct_connection_on_the_team_outranks_a_cold_manager():
    connection = score(person("Priya Raman", "referral", "direct", "peer", "title_and_team"))
    manager = score(person("Jane Doe", "manager", "cold", "team_manager", "title_and_team"))
    assert connection["score"] == 75 and manager["score"] == 55
    assert connection["parts"] == {"warmth": 40, "closeness": 15, "evidence": 20}
    result = rank([manager, connection])
    assert result["all_scored"][0]["name"] == "Priya Raman"


def test_one_pick_per_slot_and_weak_slot_stays_empty(targets):
    searches = render(targets)
    people = [
        person("Jane Doe", "manager", "cold", "team_manager", "title_and_team"),
        person("Hal Skip", "manager", "cold", "skip", "title"),
        person("Rita Recruiter", "recruiter", "cold", "recruiter_level", "title"),  # 40: not above 40
        person("Priya Raman", "referral", "direct", "peer", "title"),
        person("Al Alum", "referral", "alumni", "peer", "title"),
    ]
    result = rank(people, searches)
    assert [(p["slot"], p["name"]) for p in result["picks"]] == [("manager", "Jane Doe"), ("referral", "Priya Raman")]
    assert len(result["picks"]) <= 3
    empty = result["empty_slots"][0]
    assert empty["slot"] == "recruiter" and "Rita Recruiter at 40" in empty["reason"]
    assert [s["id"] for s in empty["search_by_hand"]] == ["recruiter", "new_hires"]
    text = report(result)
    assert "No recruiter picked" in text
    assert "direct 40" in text and "[profile](https://www.linkedin.com/in/priya-raman)" in text
    assert result["contact_order"] == ["referral", "manager"]


def test_recruiter_first_when_posting_is_flagged():
    people = [
        person("Jane Doe", "manager", "cold", "team_manager", "title_and_team"),
        person("Rita Recruiter", "recruiter", "cold", "recruiter_level", "title_and_team"),
    ]
    assert rank(people, recruiter_first=True)["contact_order"][0] == "recruiter"


def test_do_not_contact_and_bad_rows_are_left_out():
    people = [
        person("Jane Doe", "manager", "cold", "team_manager", "title_and_team"),
        person("No Link", "manager", "cold", "named", "title_and_team", profile_url=""),
        person("Bad Value", "manager", "warm", "named", "title"),
    ]
    result = rank(people, never={"jane doe"})
    assert result["picks"] == []
    reasons = {s["name"]: s["reason"] for s in result["skipped"]}
    assert "do-not-contact" in reasons["Jane Doe"] and "link the user can open" in reasons["No Link"] and "warmth" in reasons["Bad Value"]
    assert hand_search("referral", [])  == []
