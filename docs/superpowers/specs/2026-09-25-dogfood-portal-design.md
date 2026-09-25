# DOGFOOD 2026 — Portal Design Spec

**Status:** approved design, pre-kickoff. No project code written (rules-compliant).
**Kickoff:** Fri 25 Sep 2026 18:00 UTC / 23:30 IST · **Freeze:** Mon 28 Sep 2026 18:00 UTC / 23:30 IST
**Team:** solo, Python/JS generalist, AI-assisted
**Target:** clean T2 → T3, plus Normalization Proof (+5) and Threat Model (+3). Pairwise mode cut.

Supersedes the locked decisions in `ARCHITECTURE.md` where noted. Three revisions:
SQLModel → SQLAlchemy 2.0, Starlette `SessionMiddleware` → server-side sessions, no Alembic.

---

## 1. Scope and priorities

Scoring is a weighted average across four criteria (scale 0–5):

| Criterion | Weight | What drives it |
|---|---|---|
| Tier Completion & Correctness | 40% | Acceptance report passes, honestly claimed |
| Judging Integrity | 25% | Role isolation, normalization, audit trail, vote abuse |
| Adoptability & Operability | 20% | One command, seeded, documented, migration path |
| Code Quality & Innovation | 15% | Reads as idiomatic; schema a DBA would defend |

**Bonus points do not change the score.** They break ties and decide the *Best Judging Engine*
prize. So tiers and integrity strictly outrank bonus-chasing.

Priority order, in order:

1. All 7 acceptance checks PASS. This is the receipt; nothing else matters without it.
2. Judging integrity depth (T2 done properly, not broadly).
3. T3 public layer for tier height.
4. Documentation written *alongside* code, not after.
5. Bonuses: Normalization Proof, Threat Model, API First. Skip Pairwise.

**Operating principle: green report first.** Get 7/7 by Sat 22:00 IST. Everything after that
is upside, and there is always a receipt to show.

---

## 2. Acceptance suite — the real definition of done

`run.py` (organizer-provided, stdlib only) reads `.dogfood.toml` and makes **7 HTTP requests**.
There are **no fixed routes** — we declare them. It never logs in; it attaches 4 headers.

| # | Tier | Check | Expect | Our route |
|---|---|---|---|---|
| 1 | T1 | gallery is public | 200 | `GET /projects` |
| 2 | T1 | project from fixtures shown | a fixture title in body | `GET /projects` |
| 3 | T1 | closed event refuses submissions | 4xx | `POST /projects/new` |
| 4 | T2 | judge sees own scores | 200 | `GET /api/judge/scores` |
| 5 | T2 | judge cannot see peer scores | 401/403 | `GET /api/judge/scores?judge=jdg_a` |
| 6 | T2 | participant blocked | 401/403 | `GET /api/judge/scores` |
| 7 | T2 | csv export works | 200 + comma in line 1 | `GET /api/export.csv` |

### Three landmines, all confirmed by reading `run.py` and `fixtures.json`

**L1 — Check 2 only looks at the first three fixture titles.** `fixture_titles()` returns
`projects[:3]` → `Glass Signal`, `Small Meadow`, `Deep Compass`. The gallery's *first page* must
contain one. → Default gallery order is fixture/`submitted_at` order. **Never sort by score.**

**L2 — Check 3 passes only if we seed the fixture's own past close date.** The fixture event's
`submissions_close` is `2026-03-01T18:00:00Z` (in the past). Seeding our own future date makes
this check FAIL. → Seed verbatim, enforce in the backend, return 409/403.

**L3 — Check 5 is the highest-value check in the event.** The spec calls it out directly.
→ A judge may *only ever* read their own scores. Any `judge` param ≠ self is 403. Organizer may
read all. Enforced in the query layer, never in a template.

### Seeded edge cases (the spec brags about these, so they are graded)

| Case | Fixture fact | Required handling |
|---|---|---|
| Flat-rate judge | `jdg_07` Iva Petrova: 4/4/4 on every project, σ = 0 | z = 0, neutral. Never NaN, never dropped. |
| Sparse reviews | 8 projects have only 2 reviews; distribution 2/3/4/5 | Aggregate equal-weight; flag `low_confidence`, emit `SE` |
| Sparse judges | 2 judges have 1 score, 6 have 2 | n < 3 → z = 0, flag `calibrated=false` |
| Duplicate submission | `tm_07` submitted "Dry Harbour" twice (`prj_07`, `prj_41`) | Detect + surface, don't crash or silently merge |
| Empty comments | 51 of 126 scores | Optional everywhere |
| Tracks | 8 tracks; 0 cross-track scores in fixture | Strict track isolation in assignment *and* in queries |

Scale: 41 projects, 40 teams, 30 judges, 8 tracks, 126 scores, 3 criteria
(`functionality`, `quality`, `innovation`), values 2–5.

---

## 3. Stack

| Layer | Decision | Note |
|---|---|---|
| Runtime | Docker, single app container + named volume | Non-negotiable |
| Backend | **FastAPI** | Auto-OpenAPI → API First bonus nearly free |
| ORM | **SQLAlchemy 2.0 + Pydantic v2** | **REVISED from SQLModel** |
| Migrations | **None.** `create_all()` on boot + `SCHEMA_VERSION` | **REVISED from Alembic** |
| DB | SQLite (WAL), Postgres optional later | Offline constraint |
| Auth | **Server-side sessions, opaque token, HttpOnly cookie** | **REVISED from Starlette SessionMiddleware** |
| Passwords | **bcrypt directly** | **REVISED from passlib** |
| Frontend | **Jinja2 SSR + HTMX 2.0.10, vendored** | No build step |
| CSRF | `fastapi-csrf-jinja` | Unsafe methods only, so checker GETs never trip |
| Rate limit | In-process, `--workers 1` | Single instance |
| Audit | SQLAlchemy `before_flush` + SQLite triggers | Append-only enforced |

### Why SQLModel was dropped

Still `0.0.39` after five years; ~59 open PRs; roadmap items (integrated migrations, CLI) open
since Oct 2023; measurably slower than SQLAlchemy; and Pydantic 2.12 made it **silently drop
unique constraints** on `Annotated` columns. Critically, its one benefit — one class as both
table and API schema — does not apply here: we need separate read schemas (never expose
`password_hash`), separate create schemas (never accept `role` from a client), and a computed
schema for normalized scores. We'd write the Pydantic models anyway.

### Why server-side sessions, not Starlette `SessionMiddleware`

Its payload is *signed, not encrypted* — `{"role":"judge"}` base64-decodes without the secret —
and `max_age` defaults to **14 days**. Suspend a judge and their cookie still says judge for two
weeks. Since role isolation is the highest-weighted requirement, the role must be read from the
DB row on every request. Also: do not use `fastapi-sessions` (self-declared unmaintained).
Writing ~30 lines ourselves means the checker path is code we control.

### Why no Alembic

SQLite `batch_alter_table` does move-and-copy, silently drops unnamed CHECK constraints, and
loses `autoincrement`. Our data is **synthetic and re-seedable from `fixtures.json` in
milliseconds**, so the honest migration story is `create_all()` on boot, a `SCHEMA_VERSION` table
that logs loudly on mismatch, and a documented `docker compose down -v` reset. Real self-hosted
projects ship real migrations because they have years of users; we have a weekend. Freeze the
schema once the checker passes.

### Critical SQLite gotchas

- **SQLite does not enforce foreign keys by default and SQLAlchemy will not turn it on.** Need
  `PRAGMA foreign_keys=ON` on a `connect` event listener, or the join graph rots silently.
- `PRAGMA` statements are **connection-scoped**; with `QueuePool` a pool hands out handles
  without them. → `journal_mode=WAL; busy_timeout=5000;` on the `connect` hook, `timeout=30`,
  `check_same_thread=False`, **one uvicorn worker**.
- Never trust Alembic autogenerate — it cannot detect renames and emits drop+add.

---

## 4. Data model

SQLAlchemy 2.0 declarative. IDs are the fixture string IDs (`prj_01`, `jdg_07`) so the mapping
from fixture to row is auditable — a defensible choice for a judging system.

| Table | Key columns | Notes |
|---|---|---|
| `events` | `id`, `name`, `submissions_close`, `status` | `status`: draft/active/frozen. Seed fixture's past date. |
| `tracks` | `id`, `name`, `event_id` | 8 rows |
| `users` | `id`, `email`, `name`, `password_hash`, `role`, `org` | `role`: admin/organizer/judge/participant |
| `sessions` | `token_hash`, `user_id`, `expires_at`, `revoked` | **Fixed seeded tokens**, see §7 |
| `judge_profiles` | `user_id`, `track_ids` | Track scoping for judges |
| `teams` | `id`, `name`, `event_id` | 40 rows |
| `team_members` | `team_id`, `user_id` | M2M |
| `invites` | `token_hash`, `team_id`, `expires_at`, `used_at` | Invite links |
| `projects` | `id`, `team_id`, `track_id`, `title`, `summary`, `repo_url`, `submitted_at` | 41 rows |
| `rubric_criteria` | `event_id`, `key`, `label`, `weight`, `max_score` | 3 seeded, organizer-editable |
| `assignments` | `judge_id`, `project_id`, `status` | Unique (judge, project) |
| `scores` | `judge_id`, `project_id`, `criteria`(JSON), `comment` | 126 rows; unique (judge, project) |
| `normalized` | `project_id`, `raw_mean`, `final`, `rank`, `n_reviews`, `se`, `low_confidence` | Computed, not stored per-judge |
| `votes` | `user_id`, `project_id`, `weight`, `created_at` | **Unique (user, project)** |
| `comments` | `project_id`, `user_id`, `body`, `created_at` | |
| `audit_log` | `actor_id`, `action`, `entity_type`, `entity_id`, `before_json`, `after_json`, `created_at` | Append-only, 2 triggers |
| `rate_limit` | in-process only | Single container |
| `seed_state` | `key`, `checksum`, `applied_at` | Idempotent seeding |

**Duplicates:** `prj_07` and `prj_41` are the same team + same title. Store both, add a
`duplicate_of` detection surfaced in the admin UI. Never silently merge — an auditable judging
system must show what it was given.

**The fixture file is input, not our data model.** Load it, transform it, store in a schema we
can defend. `criteria` stays JSON because the rubric is organizer-configurable and a new
criterion must not require a migration.

---

## 5. Role isolation architecture

The single most heavily weighted requirement. "If I can curl another judge's scores it is not
isolation."

### Guards (`app/deps.py`)

```
get_db()            -> yields Session, rollback on exception
get_session(request)-> Session row from cookie, or None
require_user        -> 401 if none
require_role(*roles)-> depends on require_user; 403 if role not allowed
Judge  = Annotated[Session, Depends(require_role("judge"))]
```

`require_role` **depends on** `require_user`, so 401-vs-403 falls out structurally rather than
being remembered.

### The structural guarantee

**Never inject a raw DB session into a route.** A route's signature is
`me: Judge = Depends(require_role("judge"))` and nothing else — there is no unscoped session
handle to write a leaky query with.

### IDOR-safe query pattern

Identity comes from the session, never from client input; the guard *is* the `WHERE` clause:

```python
def own_score(project_id: int, me: Judge, db=Depends(get_db)):
    row = db.scalar(
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.project_id == project_id,
               Score.judge_id == me.user_id,                     # identity, not input
               Project.track_id.in_(me.judge_track_ids)))        # track isolation
    if row is None:
        raise HTTPException(403, "forbidden")
    return row
```

404 vs 403: use **403** for a valid role reaching a forbidden object (the checker accepts both;
403 is semantically right and OWASP-correct). Use 401 only when no valid session exists.

### The test that makes it a guarantee, not a convention

Walk `app.routes`; assert every route under `/judge`, `/admin`, `/organizer` has a guard in
`route.dependant.dependencies`; fail the build otherwise. Cheap, ~30 lines, and it is the single
highest-ROI test in the project.

### Three footguns that each break this check

1. **`HTTPBearer` returns 403, not 401**, for missing credentials. Use `auto_error=False` and
   raise 401 yourself.
2. **A catch-all `@app.exception_handler(Exception)` returning `TemplateResponse` drops the
   status code to 200**, erasing the 403. Pass `status_code=` explicitly; never swallow
   `HTTPException`.
3. **Router-level `dependencies=[...]` are not injectable** — you cannot read the resolved user
   from them and must re-declare `Depends` in the signature.

### Correctness matrix (from the spec's own FIG. 02)

| Actor | Own scores | Peer scores | Other track | Aggregate | Audit log |
|---|---|---|---|---|---|
| Visitor | ✗ | ✗ | ✗ | ✗ | ✗ |
| Participant | ✗ | ✗ | ✗ | ✗ | ✗ |
| Judge | + | ✗ | ✗ | ✗ | ✗ |
| Organizer | + | + | + | + | + |
| Admin | + | + | + | + | + |

A test asserts every cell.

---

## 6. Judging engine

### 6a. Normalization

**Composite first, then normalize.** One scalar per (judge, project):

```
c_ij = Σ_c (w_c · s_ijc / S_max)          # w sums to 1, S_max = 5
```

Normalizing per criterion and *then* weighting silently replaces the organizer's weights with
weights proportional to each criterion's own dispersion — it overrides organizer config and
triples the zero-σ denominators from 30 to 90.

Per-judge statistics over that judge's composites only, plus globals over all rows:

```
μ_j = mean(c_·j)      σ_j = pop_std(c_·j)      (ddof=0)
μ_g = mean(all c)     σ_g = pop_std(all c)
if σ_g == 0: all projects tie at μ_g; return early
```

Calibrate onto the **global** scale:

```
z_ij = 0                    if σ_j == 0  or  n_j < 3
z_ij = (c_ij − μ_j) / σ_j   otherwise
n_ij = μ_g + σ_g · z_ij                 # rescale — a free-floating z is NOT comparable
final_i = mean(n_ij) over assigned judges, equal weight
```

**Never leave scores as free-floating z's.** Averaging raw z's treats "2σ above her average" as
identical regardless of how spread-out each judge is, so each judge's personal scale leaks back
into the ranking. Rescaling to the global distribution is what makes the result comparable.

### 6b. Edge-case rules

| Case | Rule | Why |
|---|---|---|
| `σ_j == 0` (`jdg_07`) | `z = 0` → contributes exactly `μ_g`; flag `informative=false` | A constant-score judge carries zero information about relative quality. Neutral is the MLE for an uninformative vote. Does not reward her 4, does not punish her, no NaN. |
| `n_j == 1` | same path (σ = 0 exactly) | Sample σ is undefined at n=1. One rule catches both. |
| `n_j == 2` | `z = 0`, flag `calibrated=false` | σ computable but vacuous: any 2-point judge's z is forced to ±0.707 regardless of the real gap. |
| Project with 2 vs 5 reviews | Comparable. Equal-weight mean. Flag `low_confidence`, emit `SE = std(n_ij)/√n_i` | Precision problem, not bias. Penalising on n punishes the project for assignment luck. |
| Exact ties | sort key: (1) `final` desc at full float precision, (2) `n_reviews` desc, (3) raw weighted mean desc, (4) `project_id` asc | Deterministic and auditable; each key is inspectable. |

**Explicitly rejected:** `σ + 1e-6`. That is a neural-net gradient device, not statistics — it
injects scale-dependent bias. Detect `σ_j == 0` and apply a declared rule.

**Also rejected:** dropping the flat judge. That silently reduces that project's n and penalises
it for assignment luck.

**Optional upgrade if time allows:** shrink `σ_j` toward `σ_g` instead of the hard n<3 cut —
`σ̂_j² = (n_j/(n_j+k))·s_j² + (k/(n_j+k))·σ_g²`, k=2 (Efron–Morris).

### 6c. The Normalization Proof artifact (+5)

Four panels:

- **(A)** project × judge raw matrix, with raw rank
- **(B)** same matrix post-transform, with normalized rank
- **(C)** slopegraph raw → normalized rank, highlighting projects that moved ≥3 places, stating
  plainly whether the winner changed
- **(D)** per-judge diagnostics table: `n, μ_j, σ_j, informative, calibrated` — `jdg_07` sitting
  there at σ=0 is the proof we handled it deliberately

**The clincher: an invariance test.** Scale one judge's entire column by a constant (simulate a
lenient judge) and show the normalized ranking is **unchanged** while the raw ranking moves. That
is the defining property of the method, it is falsifiable, and it is more convincing than any
table. Ship it as a unit test.

### 6d. Judge assignment

**Corrected arithmetic:** 41 projects × 3 reviews = 123 slots ÷ 30 judges = **4.1 projects per
judge**. The panel is ~6× over-provisioned, so load balancing is trivial and **track partitioning
is the entire problem.** (The spec's "5 hours for 30 projects" implies ~10 min/project,
contradicting its own 4-minute figure.)

Algorithm — deterministic, seeded RNG, ~30 lines:

1. Partition judges by track, projects by track. **Never merge tracks** — isolation is structural.
2. **Feasibility gate per track:** `judges_t × CAP ≥ projects_t × 3`, where `CAP = 10` is the
   per-judge assignment ceiling (organizer-configurable). If any track fails, **fail
   loudly at seed time and list the under-covered projects.** Silent relaxation means a project
   ships with one review and nobody notices.
3. Per track, m projects (seeded shuffle), k judges. **Cyclic resolution:** judge *j* takes
   indices `(j + i·k) mod m` for `i = 0 … ⌈3m/k⌉−1`. The k cyclic shifts form a resolution of a
   balanced incomplete block design → load differs by ≤1 per judge, guaranteed, no search.
4. **Team-duplicate repair:** drop any (judge, project) whose team already appears in that
   judge's column; refill from the least-loaded eligible judge in the same track.
5. Store the seed for auditability — a non-seeded shuffle makes balance unreproducible.

**Guarantees:** ≥3 reviews per project (post-gate), judge load within ±1, no judge sees two
projects from one team, zero cross-track pairs.

BIBD is wrong here (existence constraints rarely hold at v=41, k=30, and it needs an ILP). Latin
squares need n² projects for orthogonality.

**Assignment generation is UX; the query filter is the security boundary.** Re-assert track
scoping in *every* judge query, because someone will hand-edit an assignment row.

Worth borrowing from Gavel: it precomputes nothing. `choose_next()` dispatches dynamically —
argmax of expected information gain, filtered by a `busy` set (item claimed by another judge
within a timeout), a `MIN_VIEWS` least-seen preference, and a per-judge ignore list. That
`busy` set is what stops two judges hitting the same project and both scores landing.

### 6e. Rubric

Organizer-configurable criteria with weights and per-criterion max. Weighted total per score
row. **Weights are stored as organizer-entered raw numbers and normalised on read** (divide by
sum, so the organizer never has to make them add to 1.0); a zero total is rejected at save time
with a 400. Weights are displayed next to each criterion in the judge console, because a judge
who cannot see the weights is guessing.

---

## 7. Seed, sessions, and `.dogfood.toml`

### Deterministic session tokens — subtle and mandatory

Tokens must be **fixed literals** (e.g. `tok_organizer_7f3a91c2`), never `secrets.token_urlsafe()`
at seed time. A judge resets with `docker compose down -v`, which re-seeds and would regenerate
random tokens — and every token in `.dogfood.toml` would 401. This is a silent, total failure.

### Idempotent seeding

Sentinel row + content checksum, not `SELECT count(*)` (can't detect a changed fixture) and not
`stamp head` (schema ≠ data):

```python
row = s.get(SeedState, "fixtures")
if row and row.checksum == sha256(FIXTURE_BYTES).hexdigest():
    log("seed: already applied"); return
with s.begin():
    ... s.merge(obj) for each ...   # merge, not add → upsert
    s.merge(SeedState(key="fixtures", checksum=..., applied_at=utcnow()))
```

**Print the 4 auth headers to stdout on every boot**, not only on first seed — the checker never
logs in, so these headers *are* the credential.

### `.dogfood.toml` (repo root, ~10 lines)

```toml
[portal]
base_url = "http://localhost:8080"

[tiers]
claimed = ["T1", "T2"]
pitch = "One sentence on what you built."

[auth]
organizer   = "Cookie: sid=tok_organizer_7f3a91c2"
judge_a     = "Cookie: sid=tok_judge_a_91bc44de"
judge_b     = "Cookie: sid=tok_judge_b_44de91bc"
participant = "Cookie: sid=tok_participant_2e88prt_"

[routes]
gallery      = "/projects"
submit       = "/projects/new"
judge_scores = "/api/judge/scores"
peer_scores  = "/api/judge/scores?judge=jdg_a"
csv_export   = "/api/export.csv"
```

---

## 8. Docker — offline guarantee

### Dockerfile strategy

Single stage. Every dependency (fastapi, uvicorn, sqlalchemy, jinja2, bcrypt, pillow) ships
manylinux wheels for x86_64 *and* aarch64, so no compiler is needed.

- `--only-binary=:all:` so pip can never fall back to an sdist (which needs gcc and a build-time
  fetch).
- `--require-hashes` — `pip freeze` records versions but not artifacts, so a yanked/re-uploaded
  sdist passes it. Caveat: it does not cover `[build-system].requires`, mitigated by
  `--only-binary`.
- `PIP_DISABLE_PIP_VERSION_CHECK=1` kills pip's unconditional self-check to PyPI.
- **No wheelhouse in the repo** — arch-specific, ~40MB, and a judge's Mac may be arm64 while
  ours is amd64.
- **Non-root with the chown before `USER`:**
  `RUN mkdir -p /data && chown -R 10001:10001 /app /data` then `USER 10001`. This ordering is
  the fix for `OperationalError: unable to open database file`.
- **Named volume, never a bind mount** — bind mounts inherit the host uid.

### `.dockerignore`

`.git`, `.venv`, `venv`, `env`, `__pycache__`, `*.py[cod]`, `*.egg-info`, `.pytest_cache`,
`.mypy_cache`, `.ruff_cache`, `htmlcov`, `.coverage`, `tests`, `docs`, `*.md`, `!README.md`,
`.env`, `.env.*`, `!.env.example`, `db.sqlite3`, `db.sqlite3-*`, `data/`, `wheelhouse/`,
`*.log`, `.DS_Store`, `.vscode`, `.idea`.

Context bloat is the #1 cause of slow/slow-invalidated builds. `.git` and `.env` are the two
never to skip.

### compose

`restart: "no"` + a healthcheck. `restart: unless-stopped` crash-loops forever with backoff and
`docker compose ps` cheerfully shows `Up` — it hides a broken boot. Bind
`127.0.0.1:${PORT:-8080}:8080`. **Never `internal: true`** — it silently kills published ports.

### Verifying offline — two layers, because they catch different leaks

```bash
# browser-side leaks (CDN <script>, Google Fonts) — invisible to --network none
grep -rnE 'https?://(unpkg|cdn|jsdelivr|fonts\.googleapis|ajax\.google)' app/templates/ static/

# server-side leaks — the only rigorous proof
docker run --rm --network none myapp python -c "import app.main"

docker compose up -d --wait && curl -sf localhost:8080/health
```

`--network none` is kernel-level proof for the server, but it is **blind to a CDN `<script>`**,
which leaks from the judge's browser. Both are required.

### Top runtime network leaks for this stack

1. CDN `<script>`/`<link>` in `base.html` — vendor htmx into `static/js/htmx.min.js`.
2. Google Fonts `<link>` — invisible in dev; use a system font stack.
3. `pip install` inside `entrypoint.sh` or `command:` — guaranteed runtime network.
4. pip version self-check — `PIP_DISABLE_PIP_VERSION_CHECK=1`.
5. `uvicorn[standard]` auto-injects observability deps — pin plain `uvicorn`.

uvicorn, SQLAlchemy, pydantic, bcrypt and Pillow themselves emit nothing.

### Top first-run failures a judge hits

1. `port is already allocated` — a stopped container still reserves the port; tell them
   `docker compose down`, not Ctrl-C.
2. `unable to open database file` — the volume-permission ordering above.
3. Crash loop shown as `Up` — `restart: "no"` + healthcheck.
4. `database is locked` — WAL + `busy_timeout` + one worker.
5. Slow first build on arm64 — `--only-binary` avoids compiling; note in the README that the
   first build is the only slow step.

---

## 9. Frontend — Jinja2 + HTMX 2.0.10

htmx **2.x** changes that matter: extensions moved out of core, `hx-on:` → `hx-on=`,
`selfRequestsOnly` now defaults `true`, `DELETE` uses query params, `hx-sse`/`hx-ws` removed.

### No dual-render

Always return a full page; select client-side. One template, one endpoint, zero branching:

```html
<body hx-boost="true" hx-target="body" hx-select="main" hx-swap="outerHTML">
  <main>…</main>
</body>
```

### Gallery search + filters

```html
<form hx-get="/projects" hx-target="#results" hx-swap="outerHTML"
      hx-trigger="input changed delay:300ms from:find input, change from:find select, submit"
      hx-push-url="true" hx-indicator="#spinner" method="get" action="/projects">
  <input name="q" type="search"> <select name="track">…</select>
  <button type="submit">Filter</button>   <!-- no-JS fallback: plain GET -->
</form>
<div id="results">…</div>
```

`hx-push-url="true"` makes results shareable. Remember L1: page 1 must contain a fixture title.

### Judge console

`<form method="post" action="/judge/score" hx-post="/judge/score" hx-trigger="change, submit"
hx-target="#save-state" hx-sync="closest form:replace">`. `hx-sync` is mandatory — without it
out-of-order autosave responses clobber newer ones. Keyboard nav via
`hx-trigger="keyup[key=='ArrowRight'] from:body"`. The form works with zero JS, which the
checker's plain POST depends on.

### Jinja2

Context-injection dependency is the right pattern. **Autoescaping only covers `.html`** — files
ending `.txt`/`.xml` or with no extension render **unescaped**. Sanitize user markdown before
`|safe`. Flash via `request.session.pop("_flash", None)` in the context dependency. Macros in
`_macros.html` imported by `base.html`.

---

## 10. CSV export, audit, rate limiting

### CSV

`StreamingResponse` with a generator, `media_type="text/csv"`,
`Content-Disposition: attachment`. **Header row first, so line 1 contains commas** — the checker
tests exactly this. Stdlib `csv`, never pandas (~50MB for 41 rows). Stream with
`yield_per(200)` rather than load-all.

CSV injection: prefix any cell starting `= + - @ \t \r \n` with `'`. Quote-only mitigation can
fail after an Excel re-save; single-quote prefix is the practical choice.

One parameterized endpoint `/api/export?stage=submissions|scores|normalized|audit` beats four, and
satisfies "CSV export at every stage".

### Audit log — `before_flush`, not service helpers

Service-layer helpers get missed. `before_flush` is the lowest-effort complete catch:

- `session.new` → INSERT rows
- `session.dirty` → UPDATE rows, guarded by `session.is_modified(obj)` or every loaded object logs
- `session.deleted` → DELETE rows
- `get_history(obj, key).deleted` gives the **before** value with **no extra SELECT**
- actor from `session.info["actor_id"]`
- mark `AuditLog` itself to skip recursion

Enforce append-only with two SQLite triggers (~6 lines, self-documenting proof):

```sql
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
```

### Rate limiting

In-process (`dict` + `time.monotonic()` under a lock, or `slowapi` with `memory://`) is correct
for a single container. **Must run `--workers 1`** or the effective limit silently multiplies by
N. Document the limits: lost on restart, per-process only.

### Voting anti-abuse (T3)

- Unique `(user_id, project_id)` constraint
- Rate limit per user
- Randomised project ordering on ballots (kills position bias)
- Results hidden from everyone but organizers during the voting window
- Duplicate detection: flag accounts created shortly before voting heavily
- Every vote in the audit log
- **Quadratic voting is the credible answer to Sybil-ish loud minorities** — n votes on one project
  costs √n in influence. This is explicitly named in the spec as the most defensible shipped
  approach, and it is cheap to implement on top of the unique constraint. Do it if time allows;
  it is a strong JUDGING.md talking point either way.

---

## 11. Module layout

```
app/
  config.py        # env config, fail-fast
  main.py          # app, lifespan, startup seed, pragma hook
  db.py            # engine, session factory, PRAGMA listener
  models.py        # SQLAlchemy tables
  schemas.py       # Pydantic (separate from models, deliberately)
  deps.py          # get_db, get_session, require_user, require_role
  security.py      # bcrypt, token hashing, session create/verify
  audit.py         # before_flush listener + triggers
  ratelimit.py     # in-process fixed window
  seed.py          # fixtures loader, deterministic tokens, header print
  services/
    scoring.py     # composite, z-score, normalization, edge rules
    assignment.py  # cyclic resolution, feasibility gate, team repair
    export.py      # CSV streaming
    voting.py      # quadratic weighting, duplicate detection
    mailer.py      # SMTP or console fallback (magic links)
  routers/
    auth.py events.py teams.py projects.py gallery.py
    judge.py admin.py voting.py api.py health.py
  templates/  static/  # Jinja2 + vendored htmx
tests/
  test_acceptance.py   # mirrors run.py's 7 checks
  test_isolation.py    # the route-walking guard test + matrix
  test_normalization.py# edge cases + invariance test
  test_seed.py
docker-compose.yml Dockerfile requirements.txt .dockerignore
.dogfood.toml LICENSE acceptance-report.txt
README.md ARCHITECTURE.md DATA-MODEL.md JUDGING.md THREAT-MODEL.md
```

---

## 12. Schedule (IST; kickoff Fri 23:30 → freeze Mon 23:30)

| Block | IST | Target | Done when |
|---|---|---|---|
| Fri night | 23:30–05:00 | Scaffold, models, db+pragmas, seed, sessions, guards, `/health` | `docker compose up` shows seeded portal |
| **Sleep** | **05:00–10:00** | 5h | |
| Sat morn | 10:00–16:00 | Gallery + submit + deadline; auth pages | `run.py` first pass (expect 3–4/7) |
| Sat aft | 16:00–22:00 | Judge console, rubric, `/api/judge/scores`, CSV export | **7/7 PASS — the gate** |
| **Sleep** | **22:00–01:00** | 3h | |
| Sat night | 01:00–08:00 | Normalization + assignment + JUDGING.md + proof artifact | rank movement demonstrable |
| **Sleep** | **08:00–12:00** | 4h | |
| Sun day | 12:00–20:00 | T3: voting, comments, randomised order, rate limit, audit log, admin dashboard | T3 coherent |
| Sun night | 20:00–23:00 | Offline verification, ARCHITECTURE/DATA-MODEL/THREAT-MODEL/README, tests, `.dogfood.toml`, acceptance report, demo video, buffer | **submitted** |

~12h sleep across 3 nights; ~50h productive. If Sat 22:00 is missed, **cut T3 entirely** and
spend the remaining time on docs and the report. A clean T2 with excellent docs outranks a
half-built T3.

**Docs are written alongside the code, not Sunday night.** ARCHITECTURE + DATA-MODEL +
JUDGING feed 20% + 25% of the score; they are deliverables, not afterthoughts.

---

## 13. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Role isolation leaks — costs the most points | Structural guard + route-walking test, written in the first block |
| 2 | Scope creep into T4 | T4 is 5 subsystems. Hard stop at T3. Gate on the Sat 22:00 checkpoint |
| 3 | Missed 7/7 by Sat 22:00 | Cut T3, not correctness. The report is the receipt |
| 4 | Docs left to Sunday night | Write ARCHITECTURE/DATA-MODEL/JUDGING as each subsystem lands |
| 5 | CDN asset breaks offline | Vendor htmx; run the grep check before freeze |
| 6 | Random seed tokens → total 401 after `down -v` | Fixed literal tokens |
| 7 | `database is locked` under load | WAL + busy_timeout + one worker |
| 8 | Catch-all error handler erases 403s | Pass `status_code=`; never swallow `HTTPException` |
| 9 | Duplicate submission surprises us | `tm_07`/`prj_41` handled explicitly from hour 0 |
| 10 | Overclaiming tiers | `claimed` in `.dogfood.toml` matches the report exactly |

---

## 14. Explicitly out of scope

Pairwise / Bradley-Terry mode (+5) — a second judging engine, wrong for one person in 72h.
Postgres. Multi-tenancy. Webhooks, embeddable widget, bulk import (T4). Mobile. i18n.
Any dependency that requires network at runtime.

---

## 15. Source references

- Spec + checker: `dogfoodhack.com/spec`, `_spec/run.py`, `_spec/fixtures.json`
- Gavel: `github.com/anishathalye/gavel`; `anishathalye.com/designing-a-better-judging-system`
- MLH judging plan: `guide.mlh.com/general-information/judging-and-submissions/judging-plan`
- HackWestern normalization: PR #782
- Efron–Morris shrinkage; MFRM (Esfandiari 2015, doi 10.18869/acadpub.ijal.18.2.77)
- OWASP: Authorization, IDOR, Session Management, CSV Injection, Password Storage cheatsheets
- SQLAlchemy: session events, SQLite dialect; Starlette middleware docs
- htmx 2.x migration guide and `hx-sync` / `hx-push-url` / `hx-trigger` docs
