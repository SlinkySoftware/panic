# PANIC Performance

Load test of the two-tier stack (panic-web, panic-server, MongoDB). Re-run with `Build/LoadTest/run.sh` (results land in
`Build/LoadTest/results/<timestamp>/`, not committed).

## Environment

| | |
|---|---|
| Host | Development VM: 12 vCPU (AMD Ryzen AI 9 HX PRO 370), 31 GB RAM, Docker 29 |
| Topology | Built images via `compose.yaml`: 1× panic-web (nginx), 2× panic-server (gunicorn `gthread`, 2 workers × 8 threads each) |
| MongoDB | The dev container (`mongo:8.3`, single node), own database `panic_loadtest` |
| Client | Locust 2.47 on the same host (CPU reported below), through panic-web on `127.0.0.1:18080` |
| Run | 2026-11-15, with the `panic_seed` search-key fix (see the end of this page) |

## Dataset and scenario

- `panic_seed --profile loadtest`: 5,000 catalog items, 50 users, 12 teams, 20 zones, 200 lists,
  60 dashboards.
- **Sessions:** 50 real server-side sessions, one per user (`mint_sessions.py`).
- **Zones:** users spread over 4 zones via `X-Forwarded-For` from a trusted peer.
- **Load:** think time 2–5 s, 2 min ramp, 15 min steady state (stats reset after the ramp).
- **Request mix:**
  - 35% dashboard view, 60% of them revalidating with `If-None-Match`
  - 15% bootstrap
  - 15% palette search (3 keystroke queries)
  - 15% catalog page or filter
  - 5% list detail
  - 5% `.rdp`
  - 10% mutations (layout save, profile save)
- **Stress run:** the same mix with no think time, 3 min.

## Results: steady state, 50 users (15 min, 20,517 requests, 0 failures)

| Request | p50 | p95 | p99 | Target p95 | |
|---|---|---|---|---|---|
| bootstrap | 8 ms | 12 ms | 19 ms | ≤ 75 ms | met |
| dashboard `200` (typical) | 7 ms | 11 ms | 14 ms | ≤ 150 ms | met |
| dashboard `200` (largest) | – | – | – | ≤ 300 ms | not measurable, see follow-up 3 |
| dashboard `304` | 8 ms | 11 ms | 13 ms | ≤ 50 ms | met |
| search (per keystroke query) | 29 ms | **140 ms** | 170 ms | ≤ 100 ms | **missed** |
| catalog page | 33 ms | **130 ms** | 170 ms | ≤ 120 ms | **missed** |
| list detail | 7 ms | 10 ms | 11 ms | ≤ 200 ms | met (5-item lists only, see follow-up 3) |
| mutations (layout / profile save) | 5–7 ms | 7–9 ms | 13–37 ms | ≤ 200 ms | met |
| `.rdp` launch | 7 ms | 10 ms | 11 ms | – | |

- **Error rate:** 0% (target < 0.1%).
- **Tail latency:** p99 ≤ 3 × p95 for every request type.
- **CPU (5 s samples, steady state):**
  - panic-server: avg 20% and p95 41% per replica (target < 70%)
  - MongoDB: avg 15%
  - panic-web: 1%
  - Locust: 3%

Average payloads:
- dashboard view: 3.2 KB
- catalog page (50 rows): 6.9 KB
- search: 4.6 KB
- bootstrap: 0.7 KB

## Saturation (stress run, no think time, 50 users)

- **Throughput:** 142 requests/s, with no failures. p50 300 ms and p95 1.0 s across all requests.
- **Bottleneck: MongoDB.** It used 3.4 cores on average, peaking at 6. The two servers used about
  1.9 cores each and web about 5%.
- **What drives it:** the text-matching requests, search and catalog `q`. A run without matching search
  terms (all other things equal) saturated at about 640 requests/s.

## Comparison with the first implementation

The first implementation loaded the whole portal on every request ([ADR-0001](../Architecture/adr/0001-web-server-mongo-split.md)).

| | First implementation (3,000 endpoints, 44 users) | Current (5,000 endpoints, 50 users) |
|---|---|---|
| Dashboard payload | 9.8 MB per request | 3.2 KB (200), 0 bytes (304) |
| Typical request time | ~190 ms | 7–8 ms p50, 11–12 ms p95 for dashboard / bootstrap |

## Open follow-ups (missed or untested targets)

1. **Catalog page p95 130 ms.** `services/catalog.list_catalog` loads every visible item (3,000+ for a
   typical user), filters the card's scope group, sorts and builds a full item view for each, then
   paginates in Python. Push the group filter, sort and skip/limit into the Mongo query, and build item
   views for the returned page only.
2. **Search p95 140 ms, and MongoDB saturation under stress.** Each keystroke query matches tokens
   against `search_keys` across catalog items, lists, dashboards and users. Profile the query plans
   (`explain`), confirm the `{search_keys: 1}` index serves the prefix match (anchored, case-sensitive
   regex), and cap the per-type candidate set before ranking.
3. **The dataset cannot exercise the "largest dashboard" and "list detail (500 items)" targets.** Every
   seeded dashboard has 3 widgets, and lists hold at most 5 items, so all dashboard views resolve under
   100 items. Extend the `loadtest` profile with a few large lists (200–500 items) on some dashboards,
   then re-run.
4. **Measurement caveat.** The steady window overlapped about a minute of test runs on the same
   host and Mongo container. The effect is small next to the misses above, but re-run on a quiet host
   before quoting final numbers.

## Fixed while testing

`panic_seed` stored fixtures without `search_keys`, so seeded data (demo and loadtest) was invisible to
palette and catalog text search. Seeded resources now get keys exactly like API-created ones
(`test_seed_search_keys.py`).
