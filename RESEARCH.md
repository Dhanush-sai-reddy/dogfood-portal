# Pre-Kickoff Research Notes

All of this is research/documentation (not code) — safe to prepare before Sept 25 18:00 UTC.

---

## 1. Score Normalization (T2 — Judging Integrity)

### The problem
Different judges calibrate differently: a "7" for Judge A = "5" for Judge B. Raw averages are unfair.

### Accepted methods

**Stack Ranking (MLH recommended)**
- Each judge ranks their assigned projects; top project gets `n` points, next gets `n-1`, etc.
- Simple, eliminates absolute-score variation entirely.
- MLH explicitly prefers this over rubric scoring for organizer simplicity.
- Ref: [MLH Judging Plan](https://guide.mlh.com/general-information/judging-and-submissions/judging-plan)

**Z-Score Normalization**
- For judge `j` with scores `x_j`: normalize to `(x_j - mean_j) / std_j`
- Centers all judges to mean=0, std=1; preserves rank within a judge's scores.
- Reference paper: PMC12191665 — "Z-score Pro" for large-scale competition scoring.
- Simple to implement: O(N) per judge after collecting all scores.

**Min-Max Rescaling**
- `(x - min_j) / (max_j - min_j)` — maps each judge's scores to [0, 1].
- Simpler than Z-score but sensitive to outliers.

**Hierarchical Bayesian Calibration**
- Newer approach (arXiv:2605.09227): fit per-scenario, per-judge corrections via a Bayesian model.
- Overkill for 72h but worth mentioning in JUDGING.md as a "future improvement."

### Recommendation
Implement **Z-score normalization** as primary method, with stack ranking as a configurable alternative. Document both in JUDGING.md.

---

## 2. Pairwise Comparison / Bradley-Terry (Bonus: +5)

### Theory
Bradley-Terry model: given pairwise comparisons, assign strength `π_i` to each project:
- `P(i beats j) = π_i / (π_i + π_j)`
- Estimate `π_i` via maximum likelihood (iterative algorithm, O(N * comparisons) per iteration)

### Key paper: Newman 2023 (arXiv:2207.00076)
- **Faster alternative to Zermelo's original 1929 algorithm** — converges in ~100x fewer iterations.
- Update rule: `π_i' = (sum_j w_ij * π_j / (π_i + π_j)) / (sum_j w_ji / (π_i + π_j))`
- Handles ties via extension (Section 6 of the paper).
- Handles all-win/loss players in a single step.

### Implementation approach
- Judges view projects in pairs, declare "project A is better than project B" (or tie).
- Run BT iteration until convergence → rank by `π_i`.
- **Gavel** (HackMIT, anishathalye/gavel) is the canonical reference — pairwise comparisons with Bayesian inference. 488 stars, used by dozens of events. AGPLv3, Python/Flask/Postgres. Study it but do NOT copy.

### For the hackathon
This is the **Pairwise Mode (+5 bonus)**. Implement a separate `pairwise` judging mode alongside the rubric mode.

---

## 3. Judge Assignment (T2)

### MLH formula for judge count
`J = ceil((P * n * t) / T)`
- P = projects, n = judges per project, t = time per project (4 min), T = total judging time

### Assignment strategies
1. **Round-robin / block assignment**: divide projects into blocks, assign judges to non-overlapping blocks. Simple, fair coverage.
2. **Balanced incomplete block design (BIBD)**: each project seen by exactly `r` judges, each judge sees exactly `k` projects. Mathematically optimal but requires knowing project count upfront.
3. **Algorithmic / greedy**: assign each judge to minimize max overlap, maximize coverage. Gavel uses this for its assignment algorithm.

### Recommendation
Implement **greedy round-robin with shuffle**: shuffle judges, shuffle projects, assign in blocks ensuring each project gets ≥3 judges and no judge sees the same project twice. Document in JUDGING.md.

---

## 4. Anti-Abuse / Anti-Sybil (T3)

### Threat model
- **Sybil voting**: one person creates many accounts to stuff votes
- **Ballot stuffing**: rapid-fire voting for one project
- **Judge collusion**: judges coordinate to boost/dock specific projects

### Accepted defenses

**SumUp (USENIX NSDI 2009)**
- Sybil-resilient vote aggregation using trust networks.
- Restricts voting power of adversaries below their attack edges.
- Ref: [SumUp paper](https://www.usenix.org/event/nsdi09/tech/full_papers/tran/tran.pdf)

**Practical measures for this platform**
- 1 vote per account per project (unique constraint)
- Rate limiting: max N votes per account per hour
- IP fingerprinting (optional, offline-friendly)
- Randomized project ordering (prevents autocorrelation bias)
- Audit trail: every vote logged with timestamp, account, IP
- Duplicate detection: flag accounts created within minutes of voting

### Recommendation
Implement: account-based uniqueness constraint, rate limiting, randomized ordering, and full audit log. These are defensible and implementable in 72h. Reference SumUp in the threat model doc.

---

## 5. Scoring Methodology (T2)

### Common rubric (from ScoreJudge / MLH consensus)
| Criterion | Typical weight |
|---|---|
| Technical execution | 25% |
| Innovation / originality | 20% |
| Impact / usefulness | 20% |
| Design / UX | 15% |
| Completeness | 10% |
| Presentation / demo | 10% |

### ScoreJudge approach (industry standard 2025)
- Each criterion gets its own maximum point value
- Raw scores sum to total — ceilings do the weighting
- Drop high/low scores per project to remove outliers
- Per-judge breakdown export for auditability

---

## 6. Reference implementations to study (NOT to copy)

| Project | Why study it |
|---|---|
| [Gavel](https://github.com/anishathalye/gavel) | Pairwise comparison judging, HackMIT reference |
| [dribdat](https://github.com/dribdat/dribdat) | Open-source hackathon platform, Python |
| [Hibiscus](https://github.com/HackSC/hibiscus) | All-in-one hackathon platform |
| [MLH Judging Spreadsheet](https://docs.google.com/spreadsheets/d/1eyfZmUMA63oG_89l6n6zpHj_o5V2xwS-gyndmTl5Z24/edit) | Judge allocation template |
| [ScoreJudge](https://scorejudge.com/) | Judging UX reference (private links, live leaderboard) |
| [HackHQ](https://hackhq.io/judging) | Rubric scoring + live results reference |

---

## 7. Auth approach (for self-hosted, offline)

**Don't use JWTs for browser sessions.** Industry consensus (2025-2026):
- JWTs are bigger, slower, and less secure than cookie-based sessions for browser auth.
- For a self-hosted platform: use **server-side sessions stored in the DB** (cookie = session ID, server holds state).
- Simpler to revoke, simpler to debug, no token expiry gymnastics.
- JWTs are fine for API keys / programmatic access (T4 API), but not for user login sessions.

**Roles to implement:**
- `admin` — full system access
- `organizer` — event CRUD, manage judges/submissions for their events
- `judge` — score assigned projects only
- `participant` — register, form teams, submit projects
- `public` — read-only gallery, no auth needed

**No external auth provider.** Email + password, bcrypt hashed, cookie-based session. That's it.

---

## 8. Docker Compose pattern (single command)

The standard pattern from self-hosted apps in 2026:

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports: ["8080:8080"]
    depends_on: [db]
    environment:
      DATABASE_URL: postgres://user:pass@db:5432/dogfood
      SESSION_SECRET: ${SESSION_SECRET:-dev-secret-change-in-prod}
    volumes:
      - uploads:/app/uploads

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: dogfood
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - pgdata:/var/lib/postgresql/data

  mailpit:  # local SMTP for dev, optional in prod
    image: axllent/mailpit
    ports: ["1025:1025", "8025:8025"]

volumes:
  pgdata:
  uploads:
```

**Key points:**
- `docker compose up` starts everything, seeds data on first run.
- Mailpit captures emails locally (UI at :8025) — no real SMTP needed.
- For truly offline: use SQLite instead of Postgres (swap the db service, change env var).
- `SEED=true` flag in env controls whether fixture data loads on startup.
- `uploads/` volume persists file storage across container restarts.

---

## 9. Certificate generation (T4)

**Python libraries:**
- `reportlab` — programmatic PDF generation, most mature
- `fpdf2` — lighter alternative, simpler API
- `Pillow` — if generating PNG certificates (template + text overlay)

**For signed/verifiable certificates (T4 bonus):**
- HMAC-SHA256 signature using server secret key
- Signature encodes: participant name, event name, result, timestamp
- Verification endpoint: POST `/api/certificates/verify` with certificate data
- Publicly verifiable without DB lookup if you include the signature in the certificate

**Recommended approach:** PNG template with Pillow for speed, add HMAC signature for verifiability.

---

## 10. Platform architecture — two layers (from AngelHack 2026 guide)

Hackathon platforms have two layers. Know which one you're building:

**Management layer (what the spec requires):**
- Registration, team formation, submissions
- Judging + scoring + normalization
- Results, certificates, CSV export
- Audit trails, admin dashboards

**Engagement layer (what wins adoption points):**
- Community voting, comments (T3)
- Gallery, project discovery
- Notifications, activity feeds

The spec weights management higher (70% of judging criteria). Nail that first. Engagement features are T3/T4 stretch goals.

---

## 11. Pre-kickoff prep checklist

**Decisions to lock now (pre-kickoff):**
- [ ] Tech stack: backend language + framework
- [ ] Database: SQLite (offline default) vs Postgres (production option)
- [ ] Auth: cookie-based sessions, email+password, bcrypt
- [ ] Normalization: Z-score primary, configurable
- [ ] Judge assignment: greedy round-robin with shuffle
- [ ] Anti-abuse: uniqueness constraint + rate limit + audit log
- [ ] Scoring rubrics: configurable per-event, per-criterion weights

**Docs to draft now (as markdown, no code):**
- [ ] Write data model draft (users, teams, events, submissions, scores, votes)
- [ ] Write JUDGING.md draft (assignment, rubric, normalization, defense)
- [ ] Write ARCHITECTURE.md draft (system design, Docker, roles)
- [ ] Write DATA-MODEL.md draft (tables, relationships, import/export)
- [ ] Prepare AI prompts for each component (auth, judging, voting, export)

**To review when spec is published (Sept 24):**
- [ ] Acceptance suite structure
- [ ] Fixture data format
- [ ] Anything the spec adds beyond what we've planned

---

## 12. Audit trails (T3)

Append-only log table. Immutable after insert — no UPDATE, no DELETE.

**Schema:**
```sql
CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY,
  actor_id    INTEGER NOT NULL,
  action      TEXT NOT NULL,        -- 'judge.scored', 'admin.overridden', etc.
  entity_type TEXT NOT NULL,        -- 'submission', 'score', 'vote'
  entity_id   INTEGER NOT NULL,
  before_json TEXT,                 -- previous state (nullable)
  after_json  TEXT,                 -- new state
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Rules:**
- Every write operation (create/update/delete) emits one audit row.
- Service layer writes the log; the DB does not enforce it (no triggers — application responsibility).
- Export: CSV dump of audit_log for submission archive (T4).
- Display: admin dashboard filterable by actor, action, date range.

---

## 13. Rate limiting (T3)

| Algorithm | How it works | Pros | Cons |
|---|---|---|---|
| **Fixed window** | Count requests per N-second window. Reject when over limit. | Simplest to implement (one counter). | Burst at window boundary: 2x traffic spike. |
| **Sliding window** | Count requests in a rolling N-second window. | Smooths boundary spike. | Slightly more state (timestamp list or weighted count). |
| **Token bucket** | Bucket fills at constant rate; each request drains one token. | Allows short bursts, most flexible. | More state (last refill time + token count). |

**Recommendation:** Fixed window with 1-minute granularity is sufficient for this platform. Store in DB:

```sql
CREATE TABLE rate_limit (
  key     TEXT NOT NULL,    -- 'ip:1.2.3.4' or 'user:42'
  action  TEXT NOT NULL,    -- 'vote', 'register', 'login'
  window  TEXT NOT NULL,    -- '2026-09-26T14:00' (minute bucket)
  count   INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (key, action, window)
);
```

Check + increment in a single query. Delete windows older than 2 hours on a cron. No Redis needed for a single-instance self-hosted app.

---

## 14. Webhooks (T4 — API First bonus)

**At-least-once delivery.** Idempotency is the receiver's problem, not the sender's.

**Delivery table:**
```sql
CREATE TABLE webhook_delivery (
  id          INTEGER PRIMARY KEY,
  event_id    TEXT NOT NULL,    -- idempotency key (unique per event)
  url         TEXT NOT NULL,
  payload     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'queued',  -- queued/delivered/failed
  attempts    INTEGER NOT NULL DEFAULT 0,
  next_retry  TEXT,             -- ISO timestamp
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Retry schedule:** immediate → +5s → +30s → +5min → mark failed (4 attempts total).

**HMAC signature:** sign every outgoing payload with `HMAC-SHA256(SECRET, body)`, send as `X-Signature-256` header. Receiver verifies to confirm authenticity.

**Event types (for the platform):**
- `event.created`, `event.started`, `event.frozen`
- `submission.created`, `submission.updated`
- `judging.scored`, `judging.finalized`
- `team.created`, `team.member_added`

---

## 15. Embeddable gallery widget (T4)

**Mechanism:** Cross-origin `<iframe>` with `src` pointing to a self-hosted route.

```html
<!-- Widget code generator outputs: -->
<iframe
  src="https://your-instance.example.com/embed/gallery?event=xxx&theme=dark"
  width="800" height="600" frameborder="0"
></iframe>
```

**Implementation:**
- Dedicated `/embed/gallery` route: renders a lightweight, self-contained page (CSS-in-JS or inline styles — no global styles bleeding).
- Theme via query param: `?theme=dark|light`.
- Data via internal API call at render time (not static — live leaderboard).
- `X-Frame-Options: ALLOWALL` (or specific origin in production) on the embed route.
- For a hosted "no-code embed": a `<script>` tag that creates the iframe dynamically (like Disqus/YouTube embed pattern).

---

## 16. Real-world platform examples (researched via websearch + exa + tavily)

### Gavel (HackMIT) — canonical reference
- **Pairwise comparisons** via Crowd-BT algorithm (Bradley-Terry model).
- Judge dispatch maximizes expected information gain — O(1) per vote, O(n) to dispatch next judge.
- Judges get **magic links** (no accounts needed) — click link, start judging immediately.
- Real-time admin panel ranks projects by Mu (inferred quality).
- Two-phase judging: initial screening → final expo round.
- Scaled to 1000-person HackMIT: 200+ projects, 100+ judges.
- Blog posts: [Designing a Better Judging System](https://anishathalye.com/designing-a-better-judging-system/), [Implementing a Scalable Judging System](https://anishathalye.com/implementing-a-scalable-judging-system/).

### Evalda-DQ (2026) — full reference implementation
- **Next.js + FastAPI + Celery + Supabase Postgres + Redis + Docker**.
- 4-phase judge pipeline: Verify → Extract → Build → Run (progressive network access).
- Scoring runs **outside** all containers (trusted process).
- Key env vars: `SUPABASE_URL`, `REDIS_PASSWORD`, `ADMIN_EMAIL/PASSWORD`, `COMPETSTART/END`, `BLIND_DURATION_HOURS`, `MAX_SUBMISSIONS_PER_TEAM`.
- `data/teams.json` seeded on startup.
- Shows full project structure: routers, services, auth, models, db, settings.

### Contest Platform (CodenWizFreak) — minimal reference
- **Flask + SQLite + Docker Compose + Judge0**.
- Single `.env` config: `JUDGE0_URL`, `ADMIN_PASSWORD`, `CONTEST_DURATION_SECONDS`, `DB_PATH`, `SECRET_KEY`.
- Routes: `participant.py`, `admin.py`, `judge.py`.
- `rm contest.db && python3 app.py` → fresh DB auto-recreated.
- Shows how simple a self-hosted platform can be.

### A.S.C. (AI-Submission-Central) — multi-tenant AI judging
- **Next.js + Python/Flask + Docker + SQLite**.
- Containerized microservices: `agent`, `github-reader`, `video-parser`.
- `docker-compose up --build` starts all three backend services + frontend.
- Multi-tenant: multiple judges run concurrent hackathons.

### HackHQ + ScoreJudge — judging UX reference
- Judges get **private links** (no accounts, no app install, no passwords).
- Per-criterion scoring with weights.
- Real-time leaderboard updates during demo day.
- Round-based judging: split panels (A/B) for parallel judging, then final round.
- Live dashboard: who has voted, completion rates per criterion, outstanding scores.

---

## 17. Standard data model (from Tavily search + real platforms)

Core tables — same pattern across all platforms:

```
events          → id, name, description, start/end, status (draft/active/frozen), created_by
teams           → id, name, event_id, members[] (FK to users), track
participants    → id, name, email, password_hash, role (admin/organizer/judge/participant), org
submissions     → id, team_id, event_id, title, description, repo_url, video_url, files[], track
judges          → id, user_id, event_id, assigned_submissions[] (many-to-many)
scores          → id, judge_id, submission_id, criteria (JSON), total, created_at
votes           → id, voter_id, submission_id, created_at
audit_log       → id, actor_id, action, entity_type, entity_id, before, after, created_at
rate_limit      → key, action, window, count
webhook_delivery → event_id, url, payload, status, attempts, next_retry
```

**Key relationships:**
- `events` has many `teams` and `submissions`
- `teams` has many `participants` (many-to-many via `team_members`)
- `judges` are assigned to `submissions` (many-to-many)
- `scores` link `judges` to `submissions` with per-criterion breakdown
- `audit_log` references any entity (polymorphic via entity_type + entity_id)

---

## 18. Tech stack recommendation (final)

**Pick based on team strength, not what's trendy.**

| Layer | Python Path | JS/TS Path |
|---|---|---|
| **Backend** | FastAPI + SQLModel | Next.js App Router (API routes) |
| **Frontend** | Jinja2 templates (SSR) | React (built into Next.js) |
| **ORM** | SQLModel (Pydantic + SQLAlchemy) | Drizzle ORM |
| **DB** | SQLite default, Postgres optional | SQLite default, Postgres optional |
| **Auth** | cookie sessions (DB-stored) | cookie sessions (DB-stored) |
| **Email** | `aiosmtplib` + console fallback | Nodemailer + console fallback |
| **Storage** | local FS (`uploads/` volume) | local FS (`uploads/` volume) |
| **Docker** | `python:3.12-slim` | `node:20-alpine` |
| **Certs** | Pillow (PNG) | sharp (PNG) |
| **Testing** | pytest + httpx | vitest + Playwright |
| **API docs** | FastAPI auto-OpenAPI | manual OpenAPI or `next-openapi` |

### Recommendation: Python (FastAPI + SQLModel + Jinja2)

**Why Python wins for a 72h self-hosted hackathon platform:**
1. **FastAPI auto-generates OpenAPI** — T4 API First bonus is nearly free.
2. **SQLite is first-class in Python** (`sqlite3` stdlib, zero config) — matches offline constraint perfectly.
3. **Pillow for certificates** is mature and well-documented.
4. **Simpler Docker image** — `python:3.12-slim` vs `node:20-alpine` (both fine, but Python has fewer npm dependency issues).
5. **All real-world examples use Python or hybrid** — Evalda-DQ uses FastAPI, Contest Platform uses Flask, A.S.C. uses Flask.
6. **No build step** — `uvicorn main:app` runs immediately. Next.js needs `next build` first.
7. **Jinja2 templates** eliminate the need for a separate frontend framework — HTML/CSS/JS served directly.

**If the team is stronger in JS/TS:** Next.js is also excellent. Drizzle + SQLite is clean. But you lose the free OpenAPI generation and add build complexity.

### Architecture stays the same either way:
- Centralized config (`config.py` or `config.ts`)
- Interfaces for pluggable env (DB, email, storage) — not pluggable algorithms
- Append-only audit log
- Fixed-window rate limiting (DB-stored)
- Server-side sessions (cookie = session ID)
- `docker compose up` → app + DB + optional Mailpit
- `SEED=true` → loads fixture data on first run
