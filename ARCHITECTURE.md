# Architecture — Self-Hostable Hackathon Platform

> Draft: pre-kickoff (no code written). Locked decisions + system overview.

## System overview

```mermaid
flowchart TD
    subgraph Roles
        A[Admin]
        O[Organizer]
        J[Judge]
        P[Participant]
        V[Visitor]
    end

    subgraph Flows
        A --> E[Event Config<br/>phases + rubric weights]
        O --> E
        E --> C{status:<br/>draft / active / frozen}
        P --> R[Register<br/>email + password / cookie session]
        P --> T[Team Formation]
        P --> S[Submit Project<br/>repo + video + files]
        J --> L[Magic Link<br/>no account needed]
        J --> G[Conflict-of-Interest<br/>pass / abstain]
        J --> RT[Rubric Score<br/>per-criterion sums]
        J --> PW[Pairwise Mode<br/>Bradley-Terry +5]
        V --> GA[Gallery]
        V --> VT[Vote<br/>1/acct + rate-limit]
    end

    subgraph Pipeline[Judging Pipeline]
        RT --> N[Z-score normalize<br/>stack-rank alt]
        PW --> N
        N --> RK[Rank + tie-break]
        RK --> FZ[Finalize on freeze]
        FZ --> AW[Awards + Certificates<br/>Pillow PNG + HMAC]
        FZ --> EX[CSV export]
    end

    subgraph DB[(Database<br/>SQLite offline / Postgres opt)]
        T1[events]
        T2[teams]
        T3[users]
        T4[submissions]
        T5[scores]
        T6[votes]
        T7[audit_log<br/>append-only]
        T8[rate_limit]
    end

    subgraph XCut[Cross-cutting]
        CFG[Env config<br/>fail-fast]
        MAIL[Mailer<br/>SMTP / console]
        STO[Storage<br/>uploads/ volume]
        SS[Server sessions]
        RL[Rate limiting]
        AL[Audit log]
    end

    subgraph Deploy[Deployment]
        DC[docker compose up]
        DC3[app container]
        DC1[db container<br/>optional]
        DC2[Mailpit<br/>optional]
        SEED[SEED flag<br/>fixture data]
    end

    subgraph Tiers[Tier Ladder]
        T1C[Base: registration, teams, submission, admin]
        T2J[Judging: rubric, assignment, finalization]
        T3P[Public: gallery, voting, audit]
        T4S[Stretch: certs, API/OpenAPI, webhooks, widget]
        BONUS[Normalization +5<br/>Pairwise +5<br/>Threat Model +3<br/>API First +3]
    end

    DB --- Round
    DT["Round-robin assign<br/>≥3 judges/project"] -.-> J

    style Deploy fill:#2d4a3e,color:#fff
    style Tiers fill:#3a2d4a,color:#fff
    style DB fill:#1f3a5f,color:#fff
    style Pipeline fill:#5f3a1f,color:#fff
    style XCut fill:#3a3f1f,color:#fff
```

## Locked decisions

| Area | Decision |
|---|---|
| Runtime | `docker compose up` starts a seeded, fully offline portal. No hosted services, no external APIs, no cloud accounts. |
| Backend | FastAPI + SQLModel (Python 3.12-slim) |
| Frontend | Jinja2 SSR templates (HTML/CSS/JS served directly, no build step) |
| Database | SQLite default (offline), Postgres optional via env |
| Auth | Cookie-based server sessions stored in DB. Email + password (bcrypt). No external provider. |
| Judge onboarding | Magic links (no accounts) — Gavel/ScoreJudge pattern |
| Normalization | Z-score primary, stack ranking configurable alternative |
| Judge assignment | Greedy round-robin with shuffle, ≥3 judges per project |
| Anti-abuse | 1 vote per account per project + fixed-window rate limit + append-only audit log |
| Email | Mailer interface: SMTP when configured, console/log fallback otherwise. Mailpit for dev. |
| Storage | Local `uploads/` volume, size/type limits |
| Certificates | Pillow PNG templates + HMAC-SHA256 signature for verifiability |
| API | OpenAPI via FastAPI (auto-generated) — T4 API First bonus |
| Config | Central env-driven config, fail-fast on misconfiguration |

## Architecture principles

1. **Pluggable environment, not pluggable algorithms.** Interfaces for DB/mailer/storage; each algorithm (normalization, assignment, anti-abuse) is implemented once.
2. **Management layer before engagement layer.** Judging, scoring, submissions win the 70% of judging criteria. Gallery/voting are T3/T4.
3. **Append-only audit everywhere.** Every write emits an audit row.
4. **Two judging modes.** Rubric (default, per-criterion sums) and Pairwise (Bradley-Terry, bonus).
5. **Finalize locks results.** After event freeze, scores cannot change except via audited admin override.

## Module layout (planned)

```
app/
  config.py          # centralized env config, fail-fast
  main.py            # FastAPI app, lifespan, startup seed
  routers/           # thin HTTP endpoints (auth, events, teams, submissions, judging, voting, admin, api)
  services/          # business logic (scoring, assignment, normalization, certificates, mailer, audit)
  models.py          # SQLModel tables
  templates/         # Jinja2 SSR pages
  static/            # css/js
  seed.py            # fixture data loader (SEED=true)
tests/
docker-compose.yml
Dockerfile
.env.example
README.md  ARCHITECTURE.md  DATA-MODEL.md  JUDGING.md
```

## Open questions (resolve at kickoff)
- Track system: field on teams/submissions (simple) vs separate table (flexible)? → likely simple field.
- Multi-event support: single event per instance (YAGNI at 72h) vs multi-tenancy? → single event default, schema stays event-agnostic.
- Tie-break rule: exact tie preference → organizer-set secondary criterion, else timestamp.

## Ref: research
Full details: `RESEARCH.md` (normalization, Bradley-Terry, assignment, anti-abuse, audit, rate-limit, webhooks, widget, stack rationale).