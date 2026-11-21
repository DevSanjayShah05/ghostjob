"""Precision check for repost links (Phase 4 acceptance: >= 90% of 50 sampled links are correct).

    uv run python -m ghostjob_pipelines.review_reposts sample            # writes review/repost_review.html
    uv run python -m ghostjob_pipelines.review_reposts score FILE.csv    # writes docs/REPOST_PRECISION.md

`sample` draws 50 links at random (seeded, so it's repeatable), split across the link types in proportion, and
writes a self-contained HTML page. For each pair, the reviewer clicks "Same job", "Different job" or "Not sure",
then downloads the answers as a CSV. `score` reads that CSV and reports precision.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from ghostjob_pipelines import db
from ghostjob_pipelines.embed import boilerplate_lines, strip_boilerplate
from ghostjob_pipelines.seeds import REPO_ROOT

SAMPLE_SIZE = 50
SEED = 20261121
OUT_HTML = REPO_ROOT / "review" / "repost_review.html"
OUT_MD = REPO_ROOT / "docs" / "REPOST_PRECISION.md"
EXCERPT_CHARS = 900
MIN_PER_TYPE = 10
LINK_TYPES = ("closed_then_reposted", "republished_while_open")


def sample_links(
    conn: psycopg.Connection, n: int = SAMPLE_SIZE, seed: int = SEED
) -> list[dict[str, Any]]:
    links = conn.execute(
        "SELECT posting_id, previous_posting_id, link_type, similarity, gap_days FROM repost_links"
        " ORDER BY posting_id, previous_posting_id"
    ).fetchall()
    rng = random.Random(seed)
    by_type: dict[str, list[tuple[Any, ...]]] = {}
    for row in links:
        by_type.setdefault(row[2], []).append(row)
    # Proportional to each type's share, but at least MIN_PER_TYPE of each (so a rare type still gets checked).
    quota = {t: min(len(rows), MIN_PER_TYPE) for t, rows in by_type.items()}
    rest = min(n, len(links)) - sum(quota.values())
    for t, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        extra = min(len(rows) - quota[t], round(rest * len(rows) / len(links)))
        quota[t] += extra
    biggest = max(by_type, key=lambda t: len(by_type[t])) if by_type else None
    if biggest:  # rounding leftovers go to the biggest type
        quota[biggest] = min(
            len(by_type[biggest]), quota[biggest] + min(n, len(links)) - sum(quota.values())
        )
    picked: list[tuple[Any, ...]] = []
    for t, rows in sorted(by_type.items()):
        picked.extend(rng.sample(rows, quota[t]))
    rng.shuffle(picked)

    out: list[dict[str, Any]] = []
    boiler_cache: dict[int, set[str]] = {}
    for new_id, old_id, link_type, sim, gap in picked:
        pair: dict[str, Any] = {}
        for role, pid in (("new", new_id), ("old", old_id)):
            r = conn.execute(
                """
                SELECT co.name, co.id, p.title, p.location, p.apply_url,
                       COALESCE(p.source_created_at, p.first_seen_at)::date, p.closed_at::date, p.is_active,
                       t.description_clean
                FROM postings p JOIN companies co ON co.id = p.company_id
                JOIN posting_text t ON t.posting_id = p.id WHERE p.id = %s
                """,
                (pid,),
            ).fetchone()
            assert r is not None
            company_id = int(r[1])
            if company_id not in boiler_cache:
                texts = [
                    x[0]
                    for x in conn.execute(
                        "SELECT t.description_clean FROM posting_text t JOIN postings p ON p.id = t.posting_id"
                        " WHERE p.company_id = %s AND p.is_active",
                        (company_id,),
                    )
                ]
                boiler_cache[company_id] = boilerplate_lines(texts)
            pair[role] = {
                "id": pid,
                "company": r[0],
                "title": r[2],
                "location": r[3],
                "url": r[4],
                "published": str(r[5]),
                "closed": str(r[6]) if r[6] else None,
                "active": r[7],
                "excerpt": strip_boilerplate(r[8], boiler_cache[company_id])[:EXCERPT_CHARS],
            }
        out.append(
            {
                "link_type": link_type,
                "similarity": round(float(sim), 3),
                "gap_days": int(gap),
                **pair,
            }
        )
    return out


def _card(p: dict[str, Any], label: str) -> str:
    status = f"closed {p['closed']}" if p["closed"] else "still open"
    return (
        f'<div class="card"><div class="label">{label}</div>'
        f"<h3>{html.escape(p['title'])}</h3>"
        f'<div class="meta">{html.escape(p["location"] or "-")} · published {p["published"]} · {status}'
        f' · <a href="{html.escape(p["url"])}" target="_blank" rel="noopener">posting</a></div>'
        f"<pre>{html.escape(p['excerpt'])}</pre></div>"
    )


def render_html(pairs: list[dict[str, Any]]) -> str:
    rows = []
    for i, pr in enumerate(pairs, 1):
        key = f"{pr['new']['id']}-{pr['old']['id']}"
        kind = (
            "Old copy closed, then this one appeared"
            if pr["link_type"] == "closed_then_reposted"
            else "Old copy still open, same job posted again"
        )
        rows.append(
            f'<section class="pair" data-key="{key}" data-type="{pr["link_type"]}">'
            f"<header><b>{i}. {html.escape(pr['new']['company'])}</b> · {kind} · {pr['gap_days']} days apart"
            f" · similarity {pr['similarity']}</header>"
            f'<div class="cards">{_card(pr["old"], "Earlier posting")}{_card(pr["new"], "Later posting")}</div>'
            '<div class="buttons">'
            '<button data-v="same">Same job (correct link)</button>'
            '<button data-v="different">Different job (wrong link)</button>'
            '<button data-v="unsure">Not sure</button></div></section>'
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>GhostJob repost review</title>
<style>
body {{ font: 15px/1.45 system-ui, sans-serif; margin: 0; background: #f9f9f7; color: #0b0b0b; }}
.top {{ position: sticky; top: 0; background: #fcfcfb; border-bottom: 1px solid #e1e0d9; padding: 12px 24px;
  display: flex; gap: 16px; align-items: center; z-index: 1; }}
main {{ max-width: 1200px; margin: 0 auto; padding: 16px 24px 80px; }}
.pair {{ background: #fcfcfb; border: 1px solid #e1e0d9; border-radius: 10px; margin: 16px 0; padding: 14px; }}
.pair.done {{ border-color: #c3c2b7; opacity: .75; }}
.cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }}
.card {{ border: 1px solid #e1e0d9; border-radius: 8px; padding: 10px; min-width: 0; }}
.card h3 {{ margin: 2px 0; font-size: 15px; }} .label {{ color: #52514e; font-size: 12px; text-transform: uppercase; }}
.meta {{ color: #52514e; font-size: 13px; margin-bottom: 6px; }}
pre {{ white-space: pre-wrap; font: 13px/1.4 system-ui, sans-serif; max-height: 220px; overflow: auto; margin: 0; }}
button {{ font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid #c3c2b7; background: #fff;
  cursor: pointer; margin-right: 6px; }}
button.on {{ background: #2a78d6; color: #fff; border-color: #2a78d6; }}
#dl {{ background: #0b0b0b; color: #fff; }}
</style></head><body>
<div class="top"><b>GhostJob · repost review</b><span id="progress"></span>
<button id="dl">Download answers (CSV)</button>
<span style="color:#52514e">Is the later posting the same job as the earlier one? Answers save automatically.</span></div>
<main>{"".join(rows)}</main>
<script>
const store = JSON.parse(localStorage.getItem("ghostjob-review") || "{{}}");
const pairs = [...document.querySelectorAll(".pair")];
function paint() {{
  let n = 0;
  for (const s of pairs) {{
    const v = store[s.dataset.key];
    s.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
    s.classList.toggle("done", !!v); if (v) n++;
  }}
  document.getElementById("progress").textContent = n + " / " + pairs.length + " answered";
}}
for (const s of pairs) s.querySelectorAll("button").forEach(b => b.onclick = () => {{
  store[s.dataset.key] = b.dataset.v; localStorage.setItem("ghostjob-review", JSON.stringify(store)); paint();
}});
document.getElementById("dl").onclick = () => {{
  const lines = ["key,link_type,answer"].concat(pairs.map(s => [s.dataset.key, s.dataset.type, store[s.dataset.key] || ""].join(",")));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\\n") + "\\n"], {{type: "text/csv"}}));
  a.download = "repost_review_answers.csv"; a.click();
}};
paint();
</script></body></html>
"""


def score(path: Path) -> dict[str, object]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    judged = [r for r in rows if r["answer"] in {"same", "different"}]
    correct = sum(r["answer"] == "same" for r in judged)
    by_type: dict[str, dict[str, int]] = {}
    for r in judged:
        t = by_type.setdefault(r["link_type"], {"judged": 0, "correct": 0})
        t["judged"] += 1
        t["correct"] += r["answer"] == "same"
    return {
        "sampled": len(rows),
        "judged": len(judged),
        "unsure_or_blank": len(rows) - len(judged),
        "correct": correct,
        "precision": round(correct / len(judged), 3) if judged else None,
        "by_type": by_type,
    }


def _worst_case(result: dict[str, object]) -> str:
    correct, sampled = result["correct"], result["sampled"]
    assert isinstance(correct, int) and isinstance(sampled, int)
    return f"{correct / sampled:.0%} ({correct} of {sampled})" if sampled else "-"


def write_report(result: dict[str, object], conn: psycopg.Connection) -> str:
    totals: dict[str, int] = {
        str(t): int(n)
        for t, n in conn.execute("SELECT link_type, count(*) FROM repost_links GROUP BY 1")
    }
    p = result["precision"]
    verdict = "PASS" if isinstance(p, float) and p >= 0.9 else "FAIL"
    lines = [
        "# Repost link precision (Phase 4)",
        "",
        f"Checked by hand on {datetime.now(UTC).date()}: {SAMPLE_SIZE} links sampled at random (seed {SEED}) from"
        f" {sum(totals.values()):,} links: in proportion to each link type, with at least {MIN_PER_TYPE} of each."
        " Target: at least 90% correct.",
        "",
        f"**Precision: {p:.0%} ({result['correct']} of {result['judged']} judged links are the same job) - {verdict}**"
        if isinstance(p, float)
        else "**No links judged.**",
        "",
        f"{result['unsure_or_blank']} marked 'not sure' or left blank (excluded). Worst case, counting those as wrong:"
        f" {_worst_case(result)}.",
        "",
        "| Link type | Links in DB | Judged | Correct | Precision |",
        "|---|---:|---:|---:|---:|",
    ]
    by_type = result["by_type"]
    assert isinstance(by_type, dict)
    for t, n in sorted(totals.items()):
        s = by_type.get(t, {"judged": 0, "correct": 0})
        prec = f"{s['correct'] / s['judged']:.0%}" if s["judged"] else "-"
        lines.append(f"| `{t}` | {n:,} | {s['judged']} | {s['correct']} | {prec} |")
    missing = [t for t in LINK_TYPES if t not in totals]
    if missing:
        lines += [
            "",
            "Not checked yet (no links of this type exist): "
            + ", ".join(f"`{t}`" for t in missing)
            + ".",
            "Re-run the sample once the daily history produces some.",
        ]
    lines += [
        "",
        "Method: `uv run python -m ghostjob_pipelines.review_reposts sample` / `score`.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines))
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    sc = sub.add_parser("score")
    sc.add_argument("csv", type=Path)
    args = ap.parse_args(argv)
    with db.connect() as conn:
        if args.cmd == "sample":
            pairs = sample_links(conn)
            OUT_HTML.parent.mkdir(exist_ok=True)
            OUT_HTML.write_text(render_html(pairs))
            (OUT_HTML.parent / "repost_review_sample.json").write_text(
                json.dumps(pairs, indent=1, default=str)
            )
            print(f"wrote {OUT_HTML} ({len(pairs)} pairs)")
        else:
            result = score(args.csv)
            print(json.dumps(result, indent=2))
            print(write_report(result, conn), "->", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
