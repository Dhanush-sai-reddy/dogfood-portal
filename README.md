# DOGFOOD portal

A submission and judging portal for a hackathon weekend, built to run offline in
one Docker container and to be checked by the organizer's own `run.py`.

## Run it

```
docker compose up -d --wait
open http://localhost:8080/projects
```

The image is `dogfood-portal:local`, the service is `portal`, and it listens on
`0.0.0.0:8080` inside the container, published on `127.0.0.1:8080`.

| Command | What it does |
|---|---|
| `PORT=9000 docker compose up -d --wait` | publish on a different host port |
| `docker compose logs portal` | the server log; the seeder logs anything it had to bend to fill a full console — team conflicts, judges over capacity, orphaned fixture scores |
| `docker compose down` | stop, keep the database volume |
| `docker compose down -v` | stop and delete the volume; the next boot re-seeds from `fixtures.json` in well under a second |

## Demo logins

Every seeded account uses the password `dogfood-demo`. The cookie is `sid`, and
the four fixed session tokens live in `FIXTURE_TOKENS` in `app/seed.py`; the same
four are the `[auth]` headers the checker replays:

| Role | Who | Cookie |
|---|---|---|
| organizer | `organizer@dogfood.test` | `sid=tok_organizer_7f3a91c2` |
| judge | Diego Herrera, `jdg_24`, tracks `trk_01` + `trk_07` | `sid=tok_judge_a_91bc44de` |
| judge | Jonas Vogel, `jdg_26`, tracks `trk_03` + `trk_01` | `sid=tok_judge_b_44de91bc` |
| participant | Priya1, `priya1@example.org`, team `tm_01` (NorthKiln) | `sid=tok_participant_2e88prt0` |

`jdg_24` and `jdg_26` are also the two busiest judges in the fixtures, so the
peer-isolation demo has a full console to look at. Nobody is created as an
organizer or a participant in the fixture file, so the seeder invents exactly
those two and derives every other role from the collection the record appears in.

## Check it

```
.venv/bin/python run.py .dogfood.toml | tee acceptance-report.txt
```

`.dogfood.toml` is the organizer's config, and the only keys `run.py` reads are
`portal.base_url`, the `[auth]` cookie header per role, the `[routes]` each check
calls, and `tiers.claimed`. Seven checks come out of it — three T1, four T2 —
against a running portal. All of them `PASS` prints
`claimed T1 T2, verified T1 T2`, because a tier is only credited when every one
of its checks passed and the claim never runs ahead of the evidence.

## What is here

| Tier | State |
|---|---|
| T1 core | built: roles and sessions, one seeded event with a real deadline, 40 seeded teams, submission and edit, public gallery with search, track filter and pagination |
| T2 judging | the isolation spine, built: a judge reads only their own scores (enforced in the query layer, not the template), track scoping, assignment rows, and the organizer's CSV export at `/api/export.csv` plus the audit view at `/admin/audit` |
| T3 public | **not built** — no voting, no comments, no public results. `run.py` contains no T3 checks, so claiming T3 would print `claimed but not verified: T3` |
| T4 stretch | not built |

T2 is partial on purpose, and the claim reflects that: assignment management,
rubric weighting, the organizer progress dashboard and a documented
harsh-versus-lenient re-normalisation are the next plan. What ships here is the
part of T2 whose absence is a correctness bug rather than a missing feature —
the one that the acceptance checker probes.

## Design notes

- **One worker, SQLite in WAL.** A second worker would multiply the in-process
  rate limiter and re-scatter the connection PRAGMAs (`journal_mode=WAL`,
  `foreign_keys=ON`, `busy_timeout=5000`, all set per connection). WAL plus a
  busy timeout is what keeps a single-worker portal from returning
  `database is locked`.
- **Server-side sessions.** The cookie holds an opaque token; only its sha256 is
  stored, so a database dump hands over no live sessions. The role comes from the
  `users` row on every request, never from the cookie.
- **CSRF by construction.** `SameSite=Lax` plus a fail-closed `Origin` check on
  mutations, rather than a per-form token library. A missing `Origin` is treated
  as same-origin because a CLI client sends none; a present one must match
  `Host`, and `Origin: null` is refused because it cannot be verified. The
  checker POSTs JSON to the submit route, and a token scheme that had to exempt
  that route would have been a bypass on exactly the route under test.
- **Guards are structural.** A guarded route receives its identity from
  `Depends`, never a raw `Session`, so there is no unscoped handle in which to
  write a leaky query. `tests/test_deps_isolation.py` walks the route tree and
  fails if any route under `/judge`, `/api/judge`, `/api/export`, `/admin` or
  `/organizer` lacks a role guard.
- **Audit log.** A `before_flush` listener records every mutation of a project,
  score or assignment with its before and after values, and the log is
  append-only in SQLite itself: an `UPDATE` or `DELETE` on `audit_log` raises.
- **Judges see one column.** Assignments are derived from the fixture score pairs
  and then topped up to three reviews per project, so a disagreement cannot exist
  without a matching score row.
- **No migrations, loudly.** `SCHEMA_VERSION` is checked on every boot; a
  mismatch says to run `docker compose down -v`, because the fixtures re-seed in
  well under a second.

## Progressive enhancement

htmx 2.0.10 is vendored at `app/static/js/htmx.min.js` and loaded from
`/static`. Every `hx-` attribute is an upgrade on top of HTML that already works,
so the portal is fully usable if the script never loads:

| Enhancement | Without JavaScript |
|---|---|
| `hx-boost` on `<body>` — every link and form becomes a same-origin fetch that swaps the page wrapper | ordinary navigation and form posts; the address bar and the back button behave exactly as the browser intends |
| gallery filter: `hx-get` on the form, 300 ms debounce, `hx-push-url` | the `Filter` button and Enter submit the same `GET /projects`; you lose live filtering, not filtering |
| `#spinner`, an `htmx-indicator` | stays invisible, which is right: no request is in flight |
| judge console: `hx-post` on change, `hx-swap="none"`, `hx-sync="closest form:replace"` | the `Save` button posts the form and the 303 reloads the console; you lose autosave and the `saving…` state, and the row's status is re-read on the next page load |

Nothing is fetched per keystroke from a third party, and nothing depends on the
swap to be correct: the server always answers with a whole page, and htmx selects
the part it wants out of it, so there is one template and one endpoint per route
and no branching on `HX-Request`. One trade-off worth naming: a boosted form POST
follows the server's redirect and swaps the result, but the address bar keeps the
pre-submit URL until the next navigation, because htmx pushes the URL it asked
for rather than the one the redirect landed on.

## Offline

Nothing fetches anything at runtime: no CDN, no Google Fonts, a system font
stack, htmx vendored with its sha256 pinned in `tests/test_offline.py`, and every
dependency pinned **and** hash-pinned with hashes compiled `--universal`, so an
arm64 laptop builds the same image.

Both layers are required, because they catch different leaks:

```
.venv/bin/python -m pytest tests/test_offline.py -q
docker run --rm --network none dogfood-portal:local python -c "import app.main"
```

`--network none` is kernel-level proof for the server and is blind to a CDN
`<script>`, which leaks from the judge's browser instead — so `tests/test_offline.py`
is the half that matters for the browser: it globs every template, stylesheet and
script in the tree at run time, fails on any absolute `http://` or `https://` in
a shipped asset, and asks the static mount for the htmx bytes rather than
trusting the path.

## Tests

```
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --only-binary :all: -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The venv is already built in this checkout, so `.venv/bin/python -m pytest -q` is
enough. Point the suite at a scratch database with
`DOGFOOD_DATABASE_URL=sqlite+pysqlite:////tmp/scratch.db` to keep it off the
real one.

## Layout

| Path | Job |
|---|---|
| `app/routers/` | one router per surface: auth, gallery, projects, judge, export, admin, health |
| `app/deps.py` | the only place a request becomes an identity |
| `app/seed.py` | fixture import, assignment derivation, the four fixed demo tokens |
| `app/services/` | logic that is not HTTP: the CSV writer |
| `app/audit.py` | the `before_flush` listener behind the audit log |
| `app/static/` | the stylesheet and the vendored htmx, both served from `/static` |
| `data/` | the SQLite file; gitignored, recreated by the seeder |
