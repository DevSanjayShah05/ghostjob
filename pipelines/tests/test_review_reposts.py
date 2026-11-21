from ghostjob_pipelines.review_reposts import render_html, score


def pair(new_id: int, old_id: int, link_type: str = "republished_while_open") -> dict:
    card = {
        "title": "Data <Analyst>",
        "location": "NYC",
        "url": "https://x/1",
        "published": "2026-06-01",
        "closed": None,
        "active": True,
        "excerpt": "Build & ship",
        "company": "Acme",
    }
    return {
        "link_type": link_type,
        "similarity": 0.97,
        "gap_days": 40,
        "new": {**card, "id": new_id},
        "old": {**card, "id": old_id},
    }


def test_render_html_escapes_and_keys_pairs():
    page = render_html([pair(2, 1), pair(4, 3, "closed_then_reposted")])
    assert 'data-key="2-1"' in page and 'data-key="4-3"' in page
    assert "Data &lt;Analyst&gt;" in page and "Build &amp; ship" in page
    assert page.startswith("<!DOCTYPE html>")


def test_score_ignores_unsure_and_blank(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text(
        "key,link_type,answer\n1-0,republished_while_open,same\n2-0,republished_while_open,different\n"
        "3-0,closed_then_reposted,same\n4-0,closed_then_reposted,unsure\n5-0,closed_then_reposted,\n"
    )
    r = score(f)
    assert (r["judged"], r["correct"], r["unsure_or_blank"]) == (3, 2, 2)
    assert r["precision"] == 0.667
    assert r["by_type"]["closed_then_reposted"] == {"judged": 1, "correct": 1}
