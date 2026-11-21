# Repost link precision (Phase 4)

Checked by hand on 2026-11-21: 50 links sampled at random (seed 20261121) from 165 links: in proportion to each link type, with at least 10 of each. Target: at least 90% correct.

**Precision: 100% (48 of 48 judged links are the same job) - PASS**

2 marked 'not sure' or left blank (excluded). Worst case, counting those as wrong: 96% (48 of 50).

| Link type | Links in DB | Judged | Correct | Precision |
|---|---:|---:|---:|---:|
| `republished_while_open` | 165 | 48 | 48 | 100% |

Not checked yet (no links of this type exist): `closed_then_reposted`.
Re-run the sample once the daily history produces some.

Method: `uv run python -m ghostjob_pipelines.review_reposts sample` / `score`.
