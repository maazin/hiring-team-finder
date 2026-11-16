"""Shared fixtures. Every person, company and posting here is made up. No test touches the network."""

import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(TESTS.parent / "scripts"))


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("HIRING_TEAM_TODAY", "2026-11-16")  # a Monday


@pytest.fixture()
def job():
    return json.loads((FIXTURES / "sample_job.json").read_text(encoding="utf-8"))


@pytest.fixture()
def master_tex():
    return (FIXTURES / "sample_master.tex").read_text(encoding="utf-8")


@pytest.fixture()
def posting(job):
    from posting import ats_extras, build_posting

    extras = ats_extras("greenhouse", {
        "first_published": "2026-11-02T09:00:00-05:00",
        "departments": [{"name": "Engineering"}, {"name": "Data Platform"}],
    })
    return build_posting(job, extras)


@pytest.fixture()
def targets(job, posting):
    from targets import build_targets

    return build_targets(job, posting)
