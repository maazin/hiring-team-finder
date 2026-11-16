"""Steps 0 to 2: freshness, ATS fields, titles."""

import pytest

from posting import ats_extras, build_posting, find_req_id, parse_job_url
from targets import build_targets, detect_seniority, peer_title, team_from_description, team_from_title


def test_greenhouse_extras_and_fresh_posting(posting):
    assert posting["team"] == "Data Platform"
    assert posting["department"] == "Engineering"
    assert posting["first_published"] == "2026-11-02"
    assert posting["age_days"] == 14
    assert posting["job_id"] == "R-4471" and posting["job_id_kind"] == "req"
    assert not posting["flagged"] and posting["ask_user"] == []


def test_lever_and_ashby_extras():
    lever = ats_extras("lever", {"categories": {"team": "Payments", "department": "Engineering"}, "createdAt": 1790000000000})
    assert (lever["team"], lever["department"]) == ("Payments", "Engineering")
    assert lever["first_published"].startswith("2026-09")
    board = {"jobs": [
        {"id": "x", "jobUrl": "https://jobs.ashbyhq.com/acme/aaa", "team": "Other"},
        {"id": "y", "jobUrl": "https://jobs.ashbyhq.com/acme/bbb", "team": "Search", "department": "Eng", "publishedAt": "2026-10-30T00:00:00Z"},
    ]}
    ashby = ats_extras("ashby", board, "bbb")
    assert (ashby["team"], ashby["first_published"][:10]) == ("Search", "2026-10-30")


def test_stale_posting_is_flagged_and_goes_recruiter_first(job):
    posting = build_posting(job, {"first_published": "2026-09-01"})
    assert posting["stale"] and posting["flagged"] and posting["recruiter_first"]
    assert "more than 30" in posting["flags"][0]


def test_repost_and_simplify_checks(job):
    seen = [{"company": "Example Co, Inc.", "title": job["title"], "job_id": "R-3990", "first_seen": "2026-08-10"}]
    listings = [{"company_name": "Example Co", "title": job["title"], "date_posted": 1793577600, "date_updated": 1793577600, "active": False}]
    posting = build_posting(job, {}, seen=seen, listings=listings)
    assert posting["repost"] == {"job_id": "R-3990", "first_seen": "2026-08-10"}
    assert posting["simplify"]["active"] is False
    assert posting["first_published"]  # fell back to SimplifyJobs' date_posted
    assert len(posting["flags"]) == 2


def test_pasted_posting_asks_for_date_and_id():
    job = {"source": "pasted", "url": "", "company": "Globex", "title": "Software Engineer I", "description_text": "Build things."}
    posting = build_posting(job)
    assert posting["job_id"] == "" and len(posting["ask_user"]) == 2
    assert build_posting(job, published="2026-11-10")["age_days"] == 6


def test_job_ids():
    assert find_req_id("Data Engineer II - Req 4471") == "4471"
    assert find_req_id("Analyst (JR-10293)") == "JR-10293"
    assert find_req_id("no id here") == ""
    assert parse_job_url("https://jobs.lever.co/acme/1b2c3d4e-0000-1111-2222-333344445555")["source"] == "lever"
    assert parse_job_url("https://acme.wd5.myworkdayjobs.com/x/job/y") == {}
    lever_job = {"url": "https://jobs.lever.co/acme/1b2c3d4e-0000-1111-2222-333344445555", "title": "SWE", "description_text": ""}
    assert build_posting(lever_job)["job_id_kind"] == "uuid"


def test_prd_example_targets(targets):
    assert targets["function"] == "Data engineering" and targets["seniority"] == "entry"
    assert targets["team"] == "Data Platform" and targets["team_source"] == "ats"
    assert targets["manager_titles"] == ["Engineering Manager, Data Platform", "Data Engineering Manager"]
    assert targets["skip_titles"] == ["Director of Data Engineering", "Head of Data"]
    assert targets["recruiter_titles"] == ["University Recruiter", "Early Career Recruiter", "Technical Recruiter"]
    assert targets["peer_title"] == "Data Engineer"
    assert targets["report_to_lines"] and "report to" in targets["report_to_lines"][0]


POSTINGS = [
    ("Data Engineer, New Grad, Data Platform", "data_engineering", "entry"),
    ("Software Engineer I", "software_engineering", "entry"),
    ("Senior Machine Learning Engineer", "machine_learning", "senior"),
    ("Data Scientist, Growth", "data_science", "mid"),
    ("Business Intelligence Analyst", "analytics", "mid"),
    ("Site Reliability Engineer II", "infrastructure", "mid"),
    ("Software Engineering Intern (Summer 2027)", "software_engineering", "entry"),
    ("Associate Product Manager", "product", "entry"),
    ("Staff Security Engineer", "security", "senior"),
    ("Analytics Engineer - University Graduate", "data_engineering", "entry"),
]


@pytest.mark.parametrize("title, function, seniority", POSTINGS)
def test_ten_postings_give_sensible_titles(title, function, seniority):
    targets = build_targets({"company": "Acme", "title": title, "description_text": ""})
    assert targets["function_key"] == function
    assert targets["seniority"] == seniority
    assert len(targets["manager_titles"]) == 2 and len(targets["skip_titles"]) == 2
    assert all("anager" in t or "Director" in t or "Head" in t for t in targets["manager_titles"])
    university = any("University" in t for t in targets["recruiter_titles"])
    assert university == (seniority == "entry")
    assert targets["peer_title"] and "New Grad" not in targets["peer_title"] and "Senior" not in targets["peer_title"]


def test_team_sources_and_unknown():
    assert team_from_title("Software Engineer, Payments") == "Payments"
    assert team_from_title("Software Engineer, Austin, TX") == ""
    assert team_from_title("Software Engineer - Remote") == ""
    assert team_from_description("You will join our Search Infrastructure team. The search infrastructure team owns ranking.") == "Search Infrastructure"
    assert team_from_description("Join our team of engineers.") == ""
    targets = build_targets({"company": "Acme", "title": "Software Engineer", "description_text": "We build things."})
    assert targets["team"] == "unknown" and targets["manager_titles"][0] == "Engineering Manager"


def test_small_company_swaps_skip_level_and_named_people():
    job = {"company": "Tiny", "title": "Backend Engineer", "description_text": ""}
    targets = build_targets(job, headcount=30, named=[{"name": "Ana Ruiz", "title": "CTO"}])
    assert targets["skip_titles"] == ["CTO", "Co-founder"] and targets["small_company"]
    assert targets["named_people"][0]["name"] == "Ana Ruiz"
    assert build_targets(job, headcount=500)["skip_titles"] == ["Director of Engineering", "VP of Engineering"]


def test_helpers():
    assert peer_title("Senior Data Engineer II - Req 4471") == "Data Engineer"
    assert detect_seniority("Software Engineer", {"seniority_level": "entry"}) == ("entry", False)
    assert detect_seniority("Software Engineering Intern") == ("entry", True)
