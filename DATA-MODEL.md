# Data model

SQLite, one file, no migrations. Nine tables, all created from the SQLAlchemy
models in `app/models.py` on first boot and re-created by the seeder in under a
second. `SCHEMA_VERSION` is checked on every boot; a mismatch tells the operator
to run `docker compose down -v` rather than to attempt a migration, because the
fixtures re-seed faster than a migration would finish.

## Schema

```
events ──┬── tracks
         ├── rubric_criteria
         └── judging_config (JSON, inline on events)

users ──┬── sessions
        ├── judge_profiles (user_id PK, track_ids JSON, capacity)
        └── team_members ──── teams ──── projects ──┬── assignments
                                                    ├── scores
                                                    └── pairwise_votes

audit_log        append-only, triggers enforce it
seed_state       fixture checksum, so a re-seed is idempotent
```

| Table | Key columns | Notes |
|---|---|---|
| `events` | `id`, `submissions_close`, `status`, `judging_config` | `judging_config` is JSON so an organizer can add a knob without a migration |
| `tracks` | `id`, `name`, `event_id` | flat, one event per deployment |
| `users` | `email` unique, `password_hash`, `role`, `org` | role is one of `admin`/`organizer`/`judge`/`participant` |
| `sessions` | `token_hash` unique, `expires_at`, `revoked` | stores the **sha256** of the cookie token, never the token |
| `judge_profiles` | `user_id` PK, `track_ids` JSON, `capacity` | a judge's track scope and workload ceiling |
| `teams` / `team_members` | composite PK on `(team_id, user_id)` | one team per participant is an application rule, not a constraint |
| `projects` | `team_id`, `track_id`, `is_draft`, `submitted_at` | `submitted_at IS NULL` means draft |
| `rubric_criteria` | `key`, `weight`, `max_score`, `position` | unique on `(event_id, key)` |
| `assignments` | `judge_id`, `project_id`, `status` | unique on `(judge_id, project_id)` |
| `scores` | `judge_id`, `project_id`, `criteria` JSON, `comment` | unique on `(judge_id, project_id)` |
| `pairwise_votes` | `project_a_id`, `project_b_id`, `winner_id` | unique on the triple; **no ranking reads this yet** |
| `audit_log` | `actor_id`, `action`, `entity_type`, `before_json`, `after_json` | append-only, see below |

## Three decisions worth defending

**A judge's identity is the session's, never the request's.** The `scores` table
is keyed `(judge_id, project_id)`, and every read of a judge's own scores filters
on `Score.judge_id == judge.id` where `judge` arrives through `Depends`. A
`?judge=` query parameter is accepted only to be compared against the session and
refused when it disagrees (`app/routers/judge.py:126`). There is no code path that
takes a judge id from a request body and uses it as a filter.

**Track scope fails closed.** `judge_track_ids` returns `[]` for a judge with no
profile rather than a wildcard, and `Project.track_id.in_([])` compiles to
`IN ()`, which is false in SQL. A misconfigured judge sees nothing instead of
everything.

**Scores cannot exist without assignments.** The seeder derives assignments from
the fixture's own score pairs and then tops them up, so a judge/project
disagreement with no matching score row is not representable. The reverse — a
score with no assignment — is blocked in `POST /judge/score`, which looks up the
assignment before it writes.

## Time

Twelve columns across eight tables are timestamps. SQLite has no timezone-aware
storage, so a plain `DateTime(timezone=True)` hands back naive values and
comparing one against `utcnow()` raises. The `UtcDateTime` type decorator converts
once, at the column boundary: naive in, aware out, and back again on write. On
disk it stays the plain `YYYY-MM-DD HH:MM:SS.ffffff` SQLite already wrote. Every
call site is therefore free of a `tzinfo` guard.

## Audit log

`app/audit.py` registers a `before_flush` listener that records every insert,
update and delete of a project, score or assignment with before and after values.
The enforcement is in SQLite, not in Python:

```sql
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
```

App-level append-only is a convention anyone with a session can skip. This raises
inside the database engine, so a stray `UPDATE` from a psql prompt, a migration,
or a future endpoint fails the same way.

## Connection PRAGMAs

Set on **every** connection, because they are connection-scoped and SQLAlchemy
pools: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`. WAL plus the
busy timeout is what keeps a single-worker portal off `database is locked` while
an export streams.

## Import and export paths

**Import** is one path, and it is the only one. `app/seed.py` reads
`fixtures.json` from the repo root on first boot, writes the reference tables, and
records a checksum in `seed_state`. Re-running is a no-op while the checksum
matches, so `docker compose up` is safe to repeat.

**Export** is two endpoints under `/api/`:

| Endpoint | Header | Access |
|---|---|---|
| `/api/export.csv` | `project_id, title, team, track, judge_id, judge_name, functionality, quality, innovation, composite, comment` | organizer, admin |
| `/api/export?stage=submissions` | `project_id, title, summary, team, track, repo_url, submitted_at` | organizer, admin |
| `/api/export?stage=scores` | same as `/api/export.csv` | organizer, admin |

`stage` is a `Literal`, so an unrecognised value is a 422 rather than a silent
fall-through. Both are `StreamingResponse` over a generator, because FastAPI
unwinds a `yield` dependency's exit stack only after the response has been sent —
the session the query is walking outlives the handler.

Two things a naive export gets wrong, both handled in
`app/services/export.py`:

*Formula injection.* Every cell is participant-controlled text. A title of
`=cmd|'/c calc'!A1` is executed by Excel on open. `safe_cell` prefixes a leading
`=`, `+`, `-`, `@`, tab, CR or LF with a single quote — the only mitigation that
survives a re-save, since quoting alone does not.

*Unbounded rows.* The export is a generator over a query walked with
`yield_per=200`, handed straight to the response body. Row count is the one number
an organizer cannot bound by hand, so the buffer is pinned to the batch size and a
row nobody asked for is never fetched.

`composite` normalises weights on read: the organizer may type `2/1/1` or
`0.5/0.25/0.25` and both mean the same rubric.

## What the schema does not model

- **No migrations.** By choice, and loudly.
- **No cross-judge normalization.** The leaderboard averages raw rubric totals.
  A strict judge and a lenient judge currently pull the same project's average in
  opposite directions, and nothing corrects for it.
- **`pairwise_votes` is write-only.** The arena records comparisons; no estimator
  consumes them, so no ranking can be recovered from that table yet.
- **No voting, comments, or public results.** T3 is not built, and the acceptance
  config claims only T1 and T2.
