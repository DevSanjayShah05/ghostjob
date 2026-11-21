import pytest

from ghostjob_pipelines.clean import (
    clean_job,
    content_hash,
    normalize_title,
    parse_salary_text,
    remote_type,
    sanitize_salary,
    seniority,
    strip_html,
    word_count,
)
from ghostjob_pipelines.models import RawJob, Salary


def test_strip_html():
    html = "<p>Hello&nbsp; <b>world</b></p><script>x()</script><ul><li>One</li><li>Two</li></ul>"
    assert strip_html(html) == "Hello world\nOne\nTwo"
    assert strip_html("") == ""


def test_word_count():
    assert word_count("Build data pipelines, 5 days a week.") == 7


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Sr. Data Analyst II", "data analyst"),
        ("Senior Software Engineer, Payments", "software engineer"),
        ("Account Executive (Hotels)", "account executive"),
        ("Manager, Data Science", "manager data science"),
        ("Staff Machine Learning Engineer - Ads", "machine learning engineer"),
        ("Data Analyst III", "data analyst"),
        ("Junior Product Designer", "product designer"),
        ("Software Engineer I", "software engineer"),
        ("Principal Product Manager | Growth", "product manager"),
        ("Head of Finance", "finance"),
        ("Director of Engineering", "engineering"),
        ("Business Operations and Growth Lead", "business operations and growth"),
        ("C++ Developer", "c++ developer"),
    ],
)
def test_normalize_title(title, expected):
    assert normalize_title(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineering Intern", "intern"),
        ("VP of Sales", "executive"),
        ("Head of Data", "executive"),
        ("Director, Product", "director"),
        ("Engineering Manager", "manager"),
        ("Product Manager", "mid"),
        ("Senior Account Manager", "senior"),
        ("Staff Engineer", "staff_plus"),
        ("Principal Data Scientist", "staff_plus"),
        ("Sr. Data Analyst", "senior"),
        ("Data Analyst III", "senior"),
        ("Junior Data Analyst", "entry"),
        ("Software Engineer I", "entry"),
        ("New Grad Software Engineer", "entry"),
        ("Data Analyst", "mid"),
    ],
)
def test_seniority(title, expected):
    assert seniority(title) == expected


@pytest.mark.parametrize(
    ("text", "lo", "hi"),
    [
        ("The range is $120,000 - $150,000 per year.", 120_000, 150_000),
        ("Pay: $120K–$150K plus equity", 120_000, 150_000),
        ("$45 - $60/hour", 45 * 2080, 60 * 2080),
        ("between $95,000 to $110,000", 95_000, 110_000),
        ("$150k-$120k", 120_000, 150_000),
    ],
)
def test_parse_salary_text(text, lo, hi):
    s = parse_salary_text(text)
    assert s is not None and (s.min, s.max, s.source) == (lo, hi, "text")


@pytest.mark.parametrize(
    "text", ["We raised $100M - $200M in funding", "No salary here", "$1 - $2", ""]
)
def test_parse_salary_text_ignores_non_pay(text):
    assert parse_salary_text(text) is None


@pytest.mark.parametrize(
    ("workplace", "location", "expected"),
    [
        ("Remote", "San Francisco", "remote"),
        ("hybrid", "New York", "hybrid"),
        ("OnSite", "Austin", "onsite"),
        ("on-site", "Austin", "onsite"),
        (None, "Remote - US", "remote"),
        (None, "New York (Hybrid)", "hybrid"),
        ("unspecified", "Denver, CO", "unknown"),
        (None, "Seattle, WA", "unknown"),
    ],
)
def test_remote_type(workplace, location, expected):
    assert remote_type(workplace, location) == expected


def test_content_hash_ignores_whitespace_and_case():
    assert content_hash("Data Analyst", "NYC", "Do  things") == content_hash(
        "data analyst", "nyc", "do things"
    )
    assert content_hash("Data Analyst", "NYC", "a") != content_hash("Data Analyst", "NYC", "b")


def test_clean_job_uses_structured_salary_first_then_text():
    raw = RawJob("1", "Sr. Data Analyst", "Remote", "<p>Pay $90,000 - $100,000</p>", "u")
    c = clean_job(raw)
    assert c.salary is not None and c.salary.source == "text" and c.salary.min == 90_000
    assert (c.title_normalized, c.seniority, c.remote_type) == ("data analyst", "senior", "remote")

    raw.salary = Salary(min=100_000, max=120_000, currency="USD", source="structured")
    assert clean_job(raw).salary == raw.salary


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (Salary(120_000, 150_000, "USD", "structured"), (120_000, 150_000)),
        (Salary(40, 40, "USD", "structured"), (40 * 2080, 40 * 2080)),  # hourly intern rate
        (Salary(62.5, 86.54, "USD", "structured"), (62.5 * 2080, 86.54 * 2080)),
        (Salary(750, 750, "USD", "structured"), None),  # placeholder, not a salary
        (Salary(0, 0, "USD", "structured"), None),
        (Salary(0, 90_000, "USD", "structured"), (None, 90_000)),
        (Salary(1_090_000, 1_500_000, "INR", "structured"), (1_090_000, 1_500_000)),
        (Salary(150_000, 120_000, "USD", "structured"), (120_000, 150_000)),
    ],
)
def test_sanitize_salary(given, expected):
    out = sanitize_salary(given)
    assert (out if out is None else (out.min, out.max)) == expected


def test_sanitize_none():
    assert sanitize_salary(None) is None
