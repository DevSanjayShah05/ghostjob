"""Cleaning: HTML -> text, title normalization, seniority, salary parsing, remote type.

Every function here is pure (no network, no database), so each one is easy to unit test.
"""

from __future__ import annotations

import hashlib
import re
import warnings
from dataclasses import dataclass

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from ghostjob_pipelines.models import RawJob, RemoteType, Salary

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# --------------------------------------------------------------------------- text


_BLOCK_TAGS = [
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "header", "footer", "blockquote", "pre",
]  # fmt: skip


def strip_html(html_text: str) -> str:
    """HTML -> readable plain text, one line per block element, collapsed whitespace."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    # Line breaks only around block elements, so inline tags (<b>, <a>) stay inside their sentence.
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text()
    lines = (re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def content_hash(title: str, location: str, description: str) -> str:
    """Fingerprint of what a job seeker actually reads. Ignores whitespace and case."""
    norm = " ".join(f"{title}\n{location}\n{description}".lower().split())
    return hashlib.sha256(norm.encode()).hexdigest()


# --------------------------------------------------------------------------- titles

SENIORITY_LEVELS = (
    "intern",
    "entry",
    "mid",
    "senior",
    "staff_plus",
    "manager",
    "director",
    "executive",
)

_ROMAN_OR_LEVEL = r"(?:i{1,3}|iv|v|vi{0,3}|l\d|level \d|\d)"
_SENIORITY_WORDS = (
    r"sr\.?|senior|jr\.?|junior|staff|principal|lead|entry[- ]level|associate|intern(?:ship)?|"
    r"new grad(?:uate)?|early career|mid[- ]level|distinguished|founding|head of|vp of|vp,?|"
    r"vice president(?: of)?|chief|director(?: of)?|sr|snr"
)
# The first comma/dash/paren segment of these words alone isn't a job title ("Manager, Data Science").
_GENERIC_HEADS = {"manager", "director", "head", "lead", "vp", "engineer", "analyst", "specialist"}
# "X Manager" roles that are individual contributors, not people managers.
_IC_MANAGER = re.compile(
    r"\b(product|program|project|account|case|customer success|community|office|partner|"
    r"marketing|campaign|content|channel|category|territory|portfolio|relationship|"
    r"implementation|release|vendor|events?)\s+manager\b"
)


def _basic(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[–—]", "-", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def seniority(title: str) -> str:
    """Rough seniority bucket from the title. A heuristic: it's tested, but it isn't perfect."""
    t = _basic(title)
    if re.search(r"\b(intern|internship|co-?op|apprentice)\b", t):
        return "intern"
    if re.search(r"\b(chief|cto|ceo|cfo|coo|cmo|vp|svp|evp|vice president|head of)\b", t):
        return "executive"
    if re.search(r"\bdirector\b", t):
        return "director"
    if re.search(r"\bmanager\b", t) and not _IC_MANAGER.search(t):
        return "manager"
    if re.search(r"\b(staff|principal|distinguished|architect)\b", t):
        return "staff_plus"
    if re.search(r"\b(sr\.?|senior|snr|lead)\b", t) or re.search(r"\b(iii|iv|l5|l6)\b", t):
        return "senior"
    if re.search(r"\b(jr\.?|junior|entry[- ]level|new grad(uate)?|early career|graduate)\b", t):
        return "entry"
    if re.search(r"\b(i|l3)\b", t) or re.search(r"\bassociate\b", t):
        return "entry"
    return "mid"


def normalize_title(title: str) -> str:
    """'Sr. Data Analyst II (Remote)' -> 'data analyst'. Used to group the same role together.

    Steps: lowercase, drop parentheses/brackets, keep the core segment before ' - ', ',', '|' or
    '/' (unless that segment is a generic word like 'Manager'), then remove seniority words and
    level numbers.
    """
    t = _basic(title)
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)
    segments = [s.strip() for s in re.split(r"\s+-\s+|,|\||\s/\s|:", t) if s.strip()]
    if not segments:
        return ""
    core = segments[0]
    head = re.sub(rf"\b({_SENIORITY_WORDS})\b", " ", core).strip()
    if len(segments) > 1 and (head in _GENERIC_HEADS or not head):
        core = f"{core} {segments[1]}"
    core = re.sub(rf"\b({_SENIORITY_WORDS})(?=\s|$)", " ", core)
    core = re.sub(rf"(?<=\s){_ROMAN_OR_LEVEL}$", " ", f" {core.strip()}")
    core = re.sub(r"[^a-z0-9+#&/ ]", " ", core)
    core = re.sub(r"\s+", " ", core).strip()
    return core or _basic(title)


# --------------------------------------------------------------------------- salary

_MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
_RANGE = re.compile(
    _MONEY + r"\s*(?:-|–|—|to)\s*" + _MONEY + r"(?:\s*(?:/|per)\s*(hour|hr|year|yr))?"
)
HOURS_PER_YEAR = 2080


def _to_number(num: str, k: str | None) -> float:
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


def parse_salary_text(text: str) -> Salary | None:
    """Find the first USD range like '$120,000 - $150,000', '$120K–$150K' or '$45 - $60/hour'.

    Returns annual USD values. Ranges that don't look like pay (under $10/hr or over $2M) are
    ignored, so funding amounts and similar numbers don't get picked up.
    """
    for m in _RANGE.finditer(text or ""):
        lo = _to_number(m.group(1), m.group(2))
        hi = _to_number(m.group(3), m.group(4))
        unit = (m.group(5) or "").lower()
        if unit in {"hour", "hr"} or hi < 300:
            lo, hi = lo * HOURS_PER_YEAR, hi * HOURS_PER_YEAR
        if lo > hi:
            lo, hi = hi, lo
        if 20_000 <= lo <= 2_000_000 and hi <= 2_000_000:
            return Salary(min=lo, max=hi, currency="USD", source="text")
    return None


# Currencies where an annual salary below this is implausible for a real full-time role.
_MAJOR_CURRENCIES = {"USD", "CAD", "EUR", "GBP", "AUD", "SGD", "CHF", "NZD"}
MIN_PLAUSIBLE_ANNUAL = 10_000
MAX_PLAUSIBLE_ANNUAL = 2_000_000


def sanitize_salary(s: Salary | None) -> Salary | None:
    """Fix the common problems in structured ATS salaries.

    - 0 means "not given".
    - Greenhouse doesn't say whether a range is hourly. Values under 300 are treated as hourly and
      annualized (x 2080).
    - In major currencies, anything still under 10,000 a year (e.g. a $750 placeholder) or over 2M (two
      numbers run together) is dropped: no salary is better than a wrong one.
    """
    if s is None:
        return None
    lo = s.min or None
    hi = s.max or None
    if lo is None and hi is None:
        return None
    top = hi if hi is not None else lo
    assert top is not None
    if top < 300:
        lo = lo * HOURS_PER_YEAR if lo is not None else None
        hi = hi * HOURS_PER_YEAR if hi is not None else None
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    if (s.currency or "USD").upper() in _MAJOR_CURRENCIES:
        top = hi if hi is not None else lo
        if top is not None and not MIN_PLAUSIBLE_ANNUAL <= top <= MAX_PLAUSIBLE_ANNUAL:
            return None
    return Salary(min=lo, max=hi, currency=s.currency, source=s.source)


# --------------------------------------------------------------------------- remote type


def remote_type(workplace_type: str | None, location: str) -> RemoteType:
    """Use the ATS's own field when it has one, then the location text. Otherwise 'unknown'.

    The description is deliberately not used: phrases like 'remote-friendly team' are too easy
    to misread.
    """
    w = (workplace_type or "").lower().replace("-", "").replace(" ", "")
    if w in {"remote"}:
        return "remote"
    if w in {"hybrid"}:
        return "hybrid"
    if w in {"onsite", "inoffice", "office"}:
        return "onsite"
    loc = location.lower()
    if "hybrid" in loc:
        return "hybrid"
    if "remote" in loc or "anywhere" in loc:
        return "remote"
    if re.search(r"\b(on-?site|in[- ]office)\b", loc):
        return "onsite"
    return "unknown"


# --------------------------------------------------------------------------- whole posting


@dataclass
class CleanJob:
    source_job_id: str
    title: str
    title_normalized: str
    seniority: str
    location: str
    remote_type: RemoteType
    department: str | None
    employment_type: str | None
    apply_url: str
    salary: Salary | None
    description_clean: str
    word_count: int
    content_hash: str


def clean_job(raw: RawJob) -> CleanJob:
    description = strip_html(raw.description_html)
    salary = sanitize_salary(raw.salary) or parse_salary_text(description)
    return CleanJob(
        source_job_id=raw.source_job_id,
        title=raw.title,
        title_normalized=normalize_title(raw.title),
        seniority=seniority(raw.title),
        location=raw.location,
        remote_type=remote_type(raw.workplace_type, raw.location),
        department=raw.department,
        employment_type=raw.employment_type,
        apply_url=raw.apply_url,
        salary=salary,
        description_clean=description,
        word_count=word_count(description),
        content_hash=content_hash(raw.title, raw.location, description),
    )
