# Judging

How a project reaches a score, who is allowed to give it, and what this
implementation does not yet do. The gaps are in the last section because they are
load-bearing — the acceptance config claims only T1 and T2, and this document
should be as honest as that claim.

## The problem this solves

Three failure modes kill hackathon judging, and all three are quiet:

1. **A judge sees a peer's scores** and anchors on them.
2. **A submission arrives after the deadline** because the client was the only
   thing enforcing it.
3. **An organizer's audit trail can be edited** by anyone with a database session.

Each is closed at the lowest layer that can actually close it, not in the template.

## Assignment strategy

`app/seed.py`, two functions: a feasibility gate and a deterministic fill.

**The gate runs first.** For each track it compares `projects × reviews_per_project`
against `judges × capacity`. If any track cannot reach its target, seeding raises
with the specific shortfall rather than producing a half-assigned console:

```
track trk_04 (Hardware): 9 projects need 27 reviews but 2 judges offer 20 slots
```

Failing loudly at boot beats a judge discovering an empty queue at 2am.

**The fill, in order:**

1. Collect every `(judge, project)` pair the fixture's own scores imply. These are
   real, already-made judgments and are never discarded.
2. **Repair team duplicates.** A judge must not see two projects from one team. When
   the fixture does, the earlier submission wins and the later score is reported as
   `orphaned_scores`. Keeping both would be a worse outcome than losing one.
3. Order projects by *shortfall first* — `-max(0, target - reviews[p])` — then by
   how few judges can cover their track, then by id. Scarce projects get the
   scarcest judges before the comfortable ones do.
4. For each project, pick from judges who are (a) scoped to its track, (b) have not
   seen its team, (c) are under capacity. Shuffle with a pinned seed and take the
   first.

**Determinism is a test, not a hope.** `ASSIGNMENT_SEED = 20260925` and
`rng.shuffle` rather than `random.sample` on an unordered set, so the same fixture
produces the same console every boot. A judge who re-runs the container and finds
their queue shuffled is looking at a bug, not a feature.

**The relaxation is counted, not hidden.** If no judge can take a project under
the team rule, the rule is dropped and `relaxations` increments. A team with many
projects can otherwise become unreachable. The count is in the `AssignmentReport`
and printed by the seeder.

There is a bug worth naming here, because it was subtle and the comment at
`app/seed.py:359` records the fix. The relaxed branch originally allowed re-picking
a judge already on the project. `pairs.add` on an existing pair is a silent no-op,
but the `load` and `reviews` counters below it would still advance — so the project
would never reach its review target while the report claimed it had. The strict
branch needs no such guard, because a judge already on a project has necessarily
already seen its team.

**Result on the shipped fixture:** 41 projects, 133 assignments, 124 submitted and
9 pending. Every project has between 3 and 5 reviews, against a target of 3.

## Scoring

Per-criterion scores, three criteria seeded (`functionality`, `quality`,
`innovation`), each with a `weight` and a `max_score` on `rubric_criteria`.

```
composite = Σ (criterion_score / max_score) × (weight / Σ weights) × max_score
```

Weights are normalised **on read** (`app/services/export.py:41`), so an organizer
who types `2/1/1` and one who types `0.5/0.25/0.25` mean the same thing. The
composite is a 0–5 number regardless of how the rubric is written.

**What an organizer can configure** at `/admin/settings`, enforced in
`POST /judge/score` rather than only in the form:

| Setting | Effect |
|---|---|
| `methodology` | `rubric` (weighted per-criterion) or `points_pool` |
| `scale_min` / `scale_max` | bounds every criterion score; outside is 422 |
| `points_pool_total` | under `points_pool`, criteria must sum **exactly** to this |
| `comment_required` | a blank comment is 422 |
| `blind_judging` | stored — see the gap section |

## Role isolation

This is the part the acceptance checker probes, so it is built to survive being
probed.

**Identity comes from `Depends`, not from a raw session.** `app/deps.py` is the
only place a request becomes an identity. A guarded route receives
`CurrentUser`/`Judge`/`Organizer` and gets `db` separately, so there is no
unscoped `Session` in a handler through which a leaky query could be written.

**The filter is the session's identity, always.** `_scoped_scores` in
`app/routers/judge.py:50` is the single query behind both the API and the console,
and it filters on `Score.judge_id == judge.id`. The `?judge=` query parameter is
accepted only to be compared and refused on mismatch
(`app/routers/judge.py:126`) — so the checker's "judge B asks for judge A's
scores" request returns 403 from the query's own premise, not from a UI hiding a
link.

**The console carries no score data of its own.** `_own_assignments` returns
assignment rows joined to projects, deliberately without score columns. Every
value the console renders comes from `own_scores`. A second query reading a peer's
score cannot be added there without it showing up on screen.

**Track scope fails closed.** `judge_track_ids` returns `[]` for a judge with no
profile; `IN ()` is false in SQL. A misconfigured judge sees nothing rather than
everything.

**Writing is gated too.** `POST /judge/score` looks up the assignment before it
writes, so a judge cannot score a project they were never given, and re-checks the
track on the way in.

`tests/test_deps_isolation.py` walks the entire route tree — including
`_IncludedRouter` and mount prefixes — and fails if any route under `/judge`,
`/api/judge`, `/api/export`, `/admin` or `/organizer` lacks a guard or admits the
wrong roles. A new unguarded route breaks the build rather than the event.

`tests/test_judge_scores.py` proves isolation by rewriting every peer's score to a
sentinel and asserting none of it appears in the API response or the rendered
console.

## Deadline enforcement

The submission form stays rendered and editable after the deadline closes. Posting
to it returns 400 and writes nothing. That is deliberate: the refusal is the
demonstration, and a hidden form would prove nothing about the server.

`Event.is_open()` is checked in the write path, comparing against
`submissions_close` in UTC.

## Auditability

Every mutation of a project, score or assignment is recorded by a `before_flush`
listener in `app/audit.py`, with actor, action, and before/after JSON. The log is
append-only **inside SQLite** — `BEFORE UPDATE` and `BEFORE DELETE` triggers
`RAISE(ABORT)`. Editing the trail requires removing a trigger, which is visible in
the schema. Visible at `/admin/audit`, exported through the CSV endpoint.

## Pairwise arena

`/pairwise` shows two randomly sampled projects side by side, with the winner
recorded in `pairwise_votes`, unique on `(judge, project_a, project_b)`, and a
server-side check that the winner is one of the two shown.

**There is no Bradley-Terry estimator.** `pairwise_votes` is write-only: nothing
reads it, so no ranking is recovered from it. The arena is a data-collection
surface, not a ranking system. The bonus challenge asks for a defensible
recoverable ranking, and that is not what ships here.

## What this does not do

Named plainly, because the acceptance suite checks the claim and honesty about
limits is rewarded:

- **No cross-judge normalization.** The leaderboard averages raw rubric totals, so
  a lenient judge inflates a project and a strict one deflates it, and nothing
  corrects for the difference. The T2 requirement and the "Normalization Proof"
  bonus are both unmet. A documented per-judge z-score, or a min-max rescale
  within each criterion, is the next piece of work.
- **`blind_judging` does nothing.** The flag is stored in `judging_config` and
  rendered in the admin form, but no read path consults it. The judge console, the
  scores API, and the leaderboard all show project titles and the leaderboard joins
  `Team.name` unconditionally. Enforcing it means suppressing team identity in
  every judge-facing read while keeping the export intact, which is a real change
  rather than a flag flip.
- **No ranking from pairwise votes.** Stated above.
- **No community voting, comments, or public results.** T3 is not built. The
  acceptance config claims `["T1", "T2"]` and prints
  `claimed T1 T2, verified T1 T2` — a tier is credited only when every one of its
  checks passed.
- **Assignment management is seed-time only.** There is no organizer UI to
  reassign a judge mid-event; `augment_assignments` runs at boot.

## What the acceptance suite verifies

`run.py` is the organizer's checker, vendored byte-identical (asserted by
`tests/test_acceptance.py`). Against a running portal it probes seven things — three
T1, four T2 — and the shipped build passes all seven:

```
T1  gallery is public ................. PASS
T1  project from fixtures shown ....... PASS
T1  closed event refuses submissions .. PASS
T2  judge sees own scores ............. PASS
T2  judge cannot see peer scores ...... PASS
T2  participant blocked ............... PASS
T2  csv export works .................. PASS
```

None of those seven touch normalization, blind judging, or the pairwise ranking.
The 7/7 is real and the gaps above are equally real.
