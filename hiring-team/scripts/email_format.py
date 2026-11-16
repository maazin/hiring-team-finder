"""Step 6: work out a company's email format from evidence. Never contacts a mail server (G3).

Runs once per company and caches the answer for 90 days:

  1. Confirm the domain receives mail with a DNS MX lookup; note the provider.
  2. Scan the company's /, /contact, /about, /team, /press and /privacy pages
     for real addresses. Drop role inboxes (info@, hr@) and junk (noreply).
  3. Add addresses the user has confirmed at that company (`learn`).
  4. Match each address to a name on the same page and to the patterns below.
     Confidence = share of named addresses that match a pattern.
  5. Give the top 3 guesses per person: best, likely or possible. With no
     evidence, the common order, all labelled possible.

A bounce (`bounce`) removes that address from later guesses; a bounce on a
best guess halves that pattern's confidence. A reply from a real address
(`learn`) is new evidence, so the next guess at that company is better.

The approach follows HireLine (page scan), Hunterly (pattern list, learning,
bounces) and Email Pattern Finder (confidence, role and junk filters). The
code is written from scratch; see THIRD_PARTY.md.

CLI (all take --cache-dir, usually "Resume Lab/cache/email-format"):
  email_format.py format --domain acme.com [--site https://acme.com] [--refresh] [--no-scan]
  email_format.py guess  --domain acme.com --name "Jane Doe" [--site ...]
  email_format.py learn  --domain acme.com --name "Jane Doe" --email jane.doe@acme.com
  email_format.py bounce --domain acme.com --name "Jane Doe" --email jdoe@acme.com [--label best]
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from shared import USER_AGENT, ascii_fold, dump_json, is_blocked_host, load_json, parse_date, today

CACHE_DAYS = 90
PAGES = ("/", "/contact", "/about", "/team", "/press", "/privacy")
MAX_BYTES = 600_000
TIMEOUT_SECONDS = 6
BOUNCE_PENALTY = 0.5

# f = first initial, l = last initial.
PATTERNS: dict[str, Callable[[str, str], str]] = {
    "first.last": lambda f, l: f"{f}.{l}",
    "first": lambda f, l: f,
    "flast": lambda f, l: f"{f[0]}{l}",
    "firstlast": lambda f, l: f"{f}{l}",
    "f.last": lambda f, l: f"{f[0]}.{l}",
    "firstl": lambda f, l: f"{f}{l[0]}",
    "first_last": lambda f, l: f"{f}_{l}",
    "last": lambda f, l: l,
    "last.first": lambda f, l: f"{l}.{f}",
    "lastfirst": lambda f, l: f"{l}{f}",
    "lastf": lambda f, l: f"{l}{f[0]}",
    "last_first": lambda f, l: f"{l}_{f}",
    "first-last": lambda f, l: f"{f}-{l}",
    "first.l": lambda f, l: f"{f}.{l[0]}",
    "first_l": lambda f, l: f"{f}_{l[0]}",
    "f_last": lambda f, l: f"{f[0]}_{l}",
    "f-last": lambda f, l: f"{f[0]}-{l}",
    "fl": lambda f, l: f"{f[0]}{l[0]}",
    "f.l": lambda f, l: f"{f[0]}.{l[0]}",
    "last.f": lambda f, l: f"{l}.{f[0]}",
    "last_f": lambda f, l: f"{l}_{f[0]}",
    "last-first": lambda f, l: f"{l}-{f}",
    "l.first": lambda f, l: f"{l[0]}.{f}",
    "lfirst": lambda f, l: f"{l[0]}{f}",
    "first-l": lambda f, l: f"{f}-{l[0]}",
    "last-f": lambda f, l: f"{l}-{f[0]}",
    "l_first": lambda f, l: f"{l[0]}_{f}",
    "l-first": lambda f, l: f"{l[0]}-{f}",
}
# Order used when there is no evidence, most common first.
COMMON_ORDER = ("first.last", "first", "flast", "firstlast", "f.last", "firstl", "first_last", "last")

ROLE_INBOXES = frozenset(
    "info hr careers career jobs job recruiting recruiter recruitment talent press media pr support help sales contact "
    "contactus hello hi hey team admin privacy legal security abuse billing accounts accounting marketing partners "
    "partnerships investors ir feedback office webmaster postmaster dpo compliance news newsletter events community "
    "success service customerservice enquiries inquiries general accessibility accommodations people founders "
    "finance payments orders returns copyright dmca trust safety ethics unsubscribe subscribe mail email".split()
)
JUNK_LOCALS = frozenset(
    "noreply no-reply no_reply donotreply do-not-reply example test user username name yourname you email youremail "
    "firstname lastname first.last firstname.lastname john.doe jane.doe johndoe janedoe john.smith jsmith jdoe".split()
)
_NAME_SUFFIX = frozenset("jr sr ii iii iv phd md mba cpa pe esq".split())
_PARTICLES = frozenset("de del della der van von la le da di dos du st".split())
_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PERSON = re.compile(r"\b([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)\s+(?:[A-Z]\.\s+)?([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)\b")


# --------------------------------------------------------------------------
# Names and patterns
# --------------------------------------------------------------------------


def split_name(name: str) -> tuple[str, str]:
    """ "Dr. María de la Cruz-Smith, PhD" -> ("maria", "delacruzsmith")."""
    text = ascii_fold(re.sub(r"\([^)]*\)", " ", name or "")).lower()
    text = re.sub(r"^(?:dr|mr|mrs|ms|prof)\.?\s+", "", text.strip())
    words = [re.sub(r"[^a-z]", "", w) for w in re.split(r"[\s,]+", text)]
    words = [w for w in words if w and w not in _NAME_SUFFIX]
    if len(words) < 2:
        return (words[0] if words else ""), ""
    last = [words[-1]]
    index = len(words) - 2
    while index >= 1 and words[index] in _PARTICLES:
        last.insert(0, words[index])
        index -= 1
    return words[0], "".join(last)


def local_for(pattern: str, first: str, last: str) -> str:
    if not first or not last:
        return first if pattern == "first" else ""
    return PATTERNS[pattern](first, last)


def matching_patterns(first: str, last: str, local: str) -> list[str]:
    if not first or not last:
        return []
    return [name for name in PATTERNS if PATTERNS[name](first, last) == local.lower()]


def shape_pattern(local: str) -> str:
    """A pattern read from the address alone, when no name on the page fits it."""
    for separator, pattern in ((".", "first.last"), ("_", "first_last"), ("-", "first-last")):
        parts = local.split(separator)
        if len(parts) == 2 and all(len(p) >= 2 and p.isalpha() for p in parts):
            return pattern
    return ""


def is_role(local: str) -> bool:
    base = re.sub(r"[\d._+-]+$", "", local.lower())
    return local.lower() in ROLE_INBOXES or base in ROLE_INBOXES


def is_junk(local: str) -> bool:
    local = local.lower()
    return local in JUNK_LOCALS or "noreply" in local.replace("-", "").replace("_", "") or local.isdigit()


# --------------------------------------------------------------------------
# Fetching company pages
# --------------------------------------------------------------------------


def _host_allowed(host: str, domain: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return bool(host) and not is_blocked_host(host) and (host == domain or host.endswith("." + domain))


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


class _SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, domain: str) -> None:
        self.domain = domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        parsed = urlparse(newurl)
        if parsed.scheme not in ("http", "https") or not _host_allowed(parsed.hostname or "", self.domain):
            return None
        if not _host_is_public(parsed.hostname or ""):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_fetch(url: str, domain: str) -> str:
    """One company page as text, or "". Only the company's own public hosts; never LinkedIn."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not _host_allowed(host, domain) or not _host_is_public(host):
        return ""
    opener = urllib.request.build_opener(_SameSiteRedirects(domain))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            kind = response.headers.get("Content-Type", "")
            if kind and not kind.startswith(("text/", "application/xhtml")):
                return ""
            return response.read(MAX_BYTES).decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def page_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text))


def addresses_in(raw: str, domain: str) -> list[str]:
    found: dict[str, None] = {}
    for match in _EMAIL.finditer(html.unescape(raw or "")):
        address = match.group(0).lower().rstrip(".")
        local, _, host = address.partition("@")
        if host == domain and not is_role(local) and not is_junk(local):
            found.setdefault(address)
    return list(found)


def scan_site(domain: str, site: str = "", fetch: Callable[[str, str], str] = safe_fetch) -> dict[str, Any]:
    base = site or f"https://{domain}"
    if "://" not in base:
        base = "https://" + base
    evidence: list[dict[str, Any]] = []
    pages: list[str] = []
    seen: set[str] = set()
    for path in PAGES:
        url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
        raw = fetch(url, domain)
        if not raw:
            continue
        pages.append(url)
        names = [split_name(f"{a} {b}") + (f"{a} {b}",) for a, b in _PERSON.findall(page_text(raw))]
        for address in addresses_in(raw, domain):
            if address in seen:
                continue
            seen.add(address)
            evidence.append(pair_address(address, names, url))
    return {"pages_scanned": pages, "evidence": evidence}


def pair_address(address: str, names: list[tuple[str, str, str]], source: str) -> dict[str, Any]:
    """Tie an address to a name on the same page; fall back to its shape."""
    local = address.split("@")[0]
    for first, last, shown in names:
        patterns = matching_patterns(first, last, local)
        if patterns:
            return {"email": address, "name": shown, "patterns": patterns, "source": source, "kind": "page"}
    shape = shape_pattern(local)
    return {"email": address, "name": "", "patterns": [shape] if shape else [], "source": source, "kind": "shape" if shape else "unnamed"}


# --------------------------------------------------------------------------
# MX
# --------------------------------------------------------------------------


def mx_lookup(domain: str, resolve: Callable[[str], list[str]] | None = None) -> dict[str, Any]:
    """Does the domain receive mail, and who hosts it. DNS only (G3)."""
    out: dict[str, Any] = {"receives_mail": None, "provider": "unknown", "hosts": [], "error": ""}
    try:
        if resolve is None:
            import dns.exception
            import dns.resolver

            try:
                answers = dns.resolver.resolve(domain, "MX", lifetime=TIMEOUT_SECONDS)
                hosts = [str(r.exchange).rstrip(".").lower() for r in sorted(answers, key=lambda r: r.preference)]
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                hosts = []
        else:
            hosts = [h.rstrip(".").lower() for h in resolve(domain)]
    except ImportError:
        out["error"] = "dnspython is not installed (pip install -r requirements.txt)"
        return out
    except Exception as exc:  # timeout, no network
        out["error"] = f"MX lookup failed: {exc}"
        return out
    hosts = [h for h in hosts if h]
    out["hosts"] = hosts
    out["receives_mail"] = bool(hosts)
    joined = " ".join(hosts)
    if "google.com" in joined or "googlemail.com" in joined:
        out["provider"] = "Google"
    elif "outlook.com" in joined or "microsoft" in joined:
        out["provider"] = "Microsoft"
    elif hosts:
        out["provider"] = "other"
    return out


# --------------------------------------------------------------------------
# Scoring and guesses
# --------------------------------------------------------------------------


def score_patterns(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Patterns with evidence, best first. Confidence = share of named addresses that match."""
    named = [e for e in state.get("confirmed", []) + state.get("evidence", []) if e.get("patterns")]
    seen: set[str] = set()
    unique = [e for e in named if not (e["email"] in seen or seen.add(e["email"]))]
    if not unique:
        return []
    penalties: dict[str, float] = {}
    for bounce in state.get("bounced", []):
        if bounce.get("penalised"):
            for pattern in bounce.get("patterns", []):
                penalties[pattern] = penalties.get(pattern, 1.0) * BOUNCE_PENALTY
    rows = []
    for pattern in PATTERNS:
        matches = [e for e in unique if pattern in e["patterns"]]
        if matches:
            rows.append({
                "pattern": pattern,
                "confidence": round(len(matches) / len(unique) * penalties.get(pattern, 1.0), 3),
                "matches": len(matches),
                "confirmed": any(e.get("kind") == "confirmed" for e in matches),
            })
    order = {name: i for i, name in enumerate(list(COMMON_ORDER) + [p for p in PATTERNS if p not in COMMON_ORDER])}
    rows.sort(key=lambda r: (-r["confidence"], order[r["pattern"]]))
    return rows


def guesses(name: str, state: dict[str, Any], count: int = 3) -> list[dict[str, Any]]:
    """The top guesses for one person, skipping addresses that already bounced."""
    first, last = split_name(name)
    if not first or not last:
        return []
    domain = state["domain"]
    scored = score_patterns(state)
    evidence_count = sum(r["matches"] for r in scored)
    bounced = {b["email"] for b in state.get("bounced", [])}
    out: list[dict[str, Any]] = []
    used: set[str] = set()

    def add(pattern: str, label: str, confidence: float) -> None:
        address = f"{local_for(pattern, first, last)}@{domain}"
        if address in used or address in bounced or len(out) >= count:
            return
        used.add(address)
        out.append({"email": address, "pattern": pattern, "label": label, "confidence": confidence})

    for rank, row in enumerate(scored):
        if rank == 0 and row["confidence"] >= 0.6 and (evidence_count >= 2 or row["confirmed"]):
            label = "best"
        elif row["confidence"] >= (0.2 if rank else 0.01):
            label = "likely"
        else:
            label = "possible"
        add(row["pattern"], label, row["confidence"])
    for pattern in COMMON_ORDER:
        add(pattern, "possible", 0.0)
    return out


# --------------------------------------------------------------------------
# The per-company cache
# --------------------------------------------------------------------------


def clean_domain(value: str) -> str:
    value = (value or "").strip().lower()
    host = urlparse(value if "://" in value else "https://" + value).hostname or ""
    return host[4:] if host.startswith("www.") else host


def state_path(cache_dir: str | Path, domain: str) -> Path:
    return Path(cache_dir) / f"{domain}.json"


def is_fresh(state: dict[str, Any]) -> bool:
    checked = parse_date(state.get("checked_on"))
    return checked is not None and (today() - checked).days <= CACHE_DAYS


def get_format(
    domain: str, cache_dir: str | Path, site: str = "", refresh: bool = False, scan: bool = True,
    fetch: Callable[[str, str], str] = safe_fetch, resolve: Callable[[str], list[str]] | None = None,
) -> dict[str, Any]:
    """The cached format for a company, built on first use and after 90 days."""
    domain = clean_domain(domain or site)
    if not domain or is_blocked_host(domain):
        raise ValueError("give the company's own mail domain, such as acme.com")
    path = state_path(cache_dir, domain)
    old = load_json(path) if path.is_file() else {}
    if old and is_fresh(old) and not refresh:
        old["cached"] = True
        old["patterns"] = score_patterns(old)
        return old
    scanned = scan_site(domain, site or old.get("site", ""), fetch) if scan else {"pages_scanned": [], "evidence": []}
    state = {
        "domain": domain,
        "site": site or old.get("site", ""),
        "checked_on": today().isoformat(),
        "cached": False,
        "mx": mx_lookup(domain, resolve),
        "pages_scanned": scanned["pages_scanned"],
        "evidence": scanned["evidence"],
        "confirmed": old.get("confirmed", []),  # what the user confirmed outlives the 90 days
        "bounced": old.get("bounced", []),
    }
    state["patterns"] = score_patterns(state)
    dump_json(state, path)
    return state


def _stored(domain: str, cache_dir: str | Path) -> dict[str, Any]:
    """The cache file as it is, or an empty one that the next `format` or `guess` fills in. No network."""
    path = state_path(cache_dir, domain)
    if path.is_file():
        return load_json(path)
    return {
        "domain": domain, "site": "", "checked_on": "", "cached": False,
        "mx": {"receives_mail": None, "provider": "unknown", "hosts": [], "error": "not checked yet"},
        "pages_scanned": [], "evidence": [], "confirmed": [], "bounced": [],
    }


def _save(state: dict[str, Any], cache_dir: str | Path) -> dict[str, Any]:
    state["patterns"] = score_patterns(state)
    dump_json({k: v for k, v in state.items() if k != "cached"} | {"cached": False}, state_path(cache_dir, state["domain"]))
    return state


def learn(domain: str, name: str, email: str, cache_dir: str | Path) -> dict[str, Any]:
    """A real address the user confirmed or got a reply from."""
    domain, email = clean_domain(domain), email.strip().lower()
    local, _, host = email.partition("@")
    if host != domain:
        raise ValueError(f"{email} is not at {domain}")
    if is_role(local) or "noreply" in local.replace("-", "").replace("_", ""):
        raise ValueError(f"{email} is a shared inbox, not a person's address")
    state = _stored(domain, cache_dir)
    first, last = split_name(name)
    entry = {"email": email, "name": name.strip(), "patterns": matching_patterns(first, last, local), "source": "user", "kind": "confirmed", "on": today().isoformat()}
    state["confirmed"] = [e for e in state.get("confirmed", []) if e["email"] != email] + [entry]
    state["bounced"] = [b for b in state.get("bounced", []) if b["email"] != email]
    return _save(state, cache_dir)


def record_bounce(domain: str, name: str, email: str, cache_dir: str | Path, label: str = "") -> dict[str, Any]:
    """A delivery failure: that address is wrong. On a best guess the pattern loses confidence too."""
    domain, email = clean_domain(domain), email.strip().lower()
    state = _stored(domain, cache_dir)
    first, last = split_name(name)
    if not any(b["email"] == email for b in state.get("bounced", [])):
        state.setdefault("bounced", []).append({
            "email": email, "patterns": matching_patterns(first, last, email.split("@")[0]),
            "penalised": label == "best", "on": today().isoformat(),
        })
    return _save(state, cache_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Company email format from evidence; no mail-server checks")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("format", "guess", "learn", "bounce"):
        p = sub.add_parser(name)
        p.add_argument("--domain", required=True)
        p.add_argument("--cache-dir", required=True)
        if name in ("format", "guess"):
            p.add_argument("--site", default="")
            p.add_argument("--refresh", action="store_true")
            p.add_argument("--no-scan", action="store_true")
        if name != "format":
            p.add_argument("--name", required=True)
        if name in ("learn", "bounce"):
            p.add_argument("--email", required=True)
        if name == "bounce":
            p.add_argument("--label", default="", choices=["", "best", "likely", "possible"])
    args = parser.parse_args(argv)
    try:
        if args.command == "learn":
            state = learn(args.domain, args.name, args.email, args.cache_dir)
        elif args.command == "bounce":
            state = record_bounce(args.domain, args.name, args.email, args.cache_dir, args.label)
        else:
            state = get_format(args.domain, args.cache_dir, args.site, args.refresh, not args.no_scan)
    except ValueError as exc:
        parser.exit(2, f"email_format: {exc}\n")
    out: dict[str, Any] = {
        "domain": state["domain"], "cached": state.get("cached", False), "checked_on": state["checked_on"],
        "mx": state["mx"], "patterns": state["patterns"][:5],
        "evidence_addresses": len(state.get("evidence", [])) + len(state.get("confirmed", [])),
    }
    if args.command != "format":
        out["name"] = args.name
        out["guesses"] = guesses(args.name, state)
    if state["mx"].get("receives_mail") is False:
        out["warning"] = f"{state['domain']} has no MX record: it does not receive mail. Check the domain."
    print(dump_json(out), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
