import pytest

from ghostjob_pipelines.seeds import SEED_CSV, read_companies

HEADER = "company_name,ats,board_token,industry,size_bucket,hq_state\n"


def test_seed_csv_is_valid_and_big_enough():
    companies = read_companies(SEED_CSV)
    assert len(companies) >= 150
    assert {c.industry for c in companies} == {
        "tech",
        "finance",
        "healthcare",
        "retail",
        "consulting",
    }
    assert {c.ats for c in companies} == {"greenhouse", "lever", "ashby"}


def test_duplicates_are_skipped(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(
        HEADER
        + "A,greenhouse,a,tech,1-200,CA\nA,lever,a2,tech,1-200,CA\nB,greenhouse,a,tech,1-200,CA\n"
    )
    assert [c.name for c in read_companies(p)] == ["A"]


@pytest.mark.parametrize(
    "row",
    ["A,workday,a,tech,1-200,CA", "A,lever,a,crypto,1-200,CA", "A,lever,a,tech,huge,CA"],
)
def test_invalid_values_rejected(tmp_path, row):
    p = tmp_path / "c.csv"
    p.write_text(HEADER + row + "\n")
    with pytest.raises(ValueError):
        read_companies(p)


def test_missing_column_rejected(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("company_name,ats\nA,lever\n")
    with pytest.raises(ValueError, match="missing columns"):
        read_companies(p)
