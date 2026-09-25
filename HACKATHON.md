# Dogfood 2026 — 72-Hour Hackathon

All that you need to know about Dogfood.

## About the Hackathon

**Dogfood 2026** is a 72-hour online hackathon built around one challenge: **build the platform that will judge you.**

Hackathon Raptors has run 35+ hackathons across 85+ countries, and this challenge comes directly from the problems encountered while running them. Registration, team formation, submissions, eligibility, judge assignment, scoring, normalization, results, certificates, and archiving all form one complex data pipeline.

**Your challenge:** build a modern, open-source, self-hostable hackathon submission and judging platform that handles this entire lifecycle.

- Everyone builds the same product against the same published specification. There are no tracks.
- This is not a hackathon where you build a demo of a platform. We are asking you to build ours.
- The winning project will be forked, self-hosted, and put into production for Hackathon Raptors events.
- You keep ownership of your work, and the project remains open source.
- The platform must run locally with a single command: `docker compose up` seeds itself with fixture data and works without a cloud account, hosted database, authentication provider, external API, or network connection.

### Stay Updated

All announcements, specification releases, rule clarifications, fixture data, acceptance suite updates, submission instructions, FAQs, and live support happen through the official Hackathon Raptors Discord.

- **Discord:** [Hackathon Raptors Discord](https://discord.gg/hackathonraptors)
- **Event Website:** https://dogfoodhack.com
- **Organizer:** [raptors.dev](https://raptors.dev)

## Why Participate

Hackathon platforms have largely converged on the same basic features. The interesting engineering problems are what happens underneath them:

- Fair judging
- Role isolation
- Score normalization
- Abuse prevention
- Reliable data flows
- APIs
- Software that an organizer can actually self-host and operate

Participants will get to:

- Build a complete hackathon platform from registration through results.
- Work on authentication, authorization, teams, submissions, galleries, dashboards, and exports.
- Design backend-enforced role isolation and permission systems.
- Build weighted and configurable judging rubrics.
- Solve cross-judge score normalization.
- Design fairer community voting and anti-abuse mechanisms.
- Work with assignment algorithms, ranking systems, and statistical methods.
- Build an API-first, self-hostable platform.
- Practice production-oriented DevOps and local deployment.
- Create software that may actually be used in future Hackathon Raptors events.
- Demonstrate engineering judgment, technical depth, and ability to ship under constraints.

> AI coding assistants are allowed and expected. The challenge is not whether AI helped. It is whether you can ship, test, explain, and defend what you built.

## Eligibility

Dogfood is open to:

- Students
- Software developers
- Engineers
- Researchers
- Professionals
- Open-source contributors
- Full-stack developers
- Backend and API engineers
- Frontend and design-system builders
- Data and algorithms enthusiasts
- Security engineers
- DevOps and self-hosting enthusiasts
- Anyone interested in building serious software, from any country

## Team Size

- **1–4 members**
- Solo participation is allowed
- Teams of 2–4 are recommended
- Cross-college teams are allowed
- Cross-disciplinary teams are allowed

## Event Format

The hackathon runs entirely online for **72 hours**. Every team builds the same product: an open-source, self-hostable hackathon submission and judging platform.

During the event, teams are expected to:

1. Design and implement the platform against the published specification.
2. Build the required core functionality.
3. Implement judging, scoring, normalization, and role isolation.
4. Test the platform against edge cases and failure scenarios.
5. Run the provided acceptance suite against their implementation.
6. Document the architecture, data model, judging system, and technical decisions.
7. Verify that the project can run locally without hosted-service dependencies.
8. Prepare a working demonstration.
9. Submit the required source code, documentation, acceptance report, and demo video.

## Tier Ladder

There are four tiers. Everyone builds against the same specification, and teams are evaluated based on how far they climb and how correctly they implement each tier.

### T1 — Core

Authentication and sessions, participant/judge/organizer/admin roles, event creation, configurable dates, tracks and prizes, team formation through invite links, project submission with draft and edit functionality, deadline enforcement, and a searchable public gallery.

> **T1 is the minimum requirement to be judged.**

### T2 — Judging

Judge invitation and assignment, batch or algorithmic assignment, weighted and configurable judging rubrics, backend-enforced role isolation, judge progress dashboards, cross-judge score normalization, and CSV export throughout the workflow.

### T3 — Public

Configurable community voting, comments, hidden results during voting, randomized project ordering, rate limiting, duplicate detection, audit trails, or an alternative voting mechanism that can be technically defended.

### T4 — Stretch

REST API and webhooks covering UI actions, certificate and record generation, signed and publicly verifiable judge participation records, an embeddable gallery widget, and bulk import and export.

> A clean, correct T2 is better than a broken T4. Tier claims are verified through the acceptance suite, not through the README.

## What Counts as Done

Your project must produce a working portal from a single command.

- `docker compose up` must start a **seeded, working portal** locally.
- The project must **not** depend on:
  - Hosted databases
  - Authentication-as-a-service
  - External APIs
  - Cloud accounts
  - Proprietary services
  - Network connectivity
- The acceptance suite will run against your build and produce a tier-by-tier pass report.
- The acceptance report must be included in your public repository.
- If the project cannot run on a laptop with the network turned off, it cannot be adopted.

## AI Tools

AI coding assistants are allowed and expected, including Claude Code, Cursor, Aider, GitHub Copilot, local AI models, and others.

- AI usage itself is not scored.
- We evaluate whether the final implementation works, whether the architecture and data model are sound, and whether the team can explain and defend the software it built.

## What You Need to Submit

Each team must submit:

- Public GitHub repository
- OSI-approved open-source license
- Working implementation
- `docker compose up` setup that starts a seeded portal
- `acceptance-report.txt`
- `README.md`
- `ARCHITECTURE.md`
- `DATA-MODEL.md`
- `JUDGING.md`
- Tests
- 5-minute demo video showing one complete event lifecycle

> Your `JUDGING.md` should explain your judge assignment strategy, scoring methodology, normalization method, and the reasoning behind your approach.
> Your `ARCHITECTURE.md` should explain the system design and major technical decisions.
> Your `DATA-MODEL.md` should document the schema and import/export paths.

## Judging Criteria

| Criterion | Weight |
|---|---|
| Tier Completion & Correctness | 40% |
| Judging Integrity | 25% |
| Adoptability & Operability | 20% |
| Code Quality & Innovation | 15% |

- **Tier Completion & Correctness (40%):** How far up the tier ladder the project reaches, verified by the acceptance suite. Correctness matters more than feature count, and honest gap reporting is rewarded.
- **Judging Integrity (25%):** How well the platform handles role isolation, judge assignment, score normalization, auditability, and voting abuse. The judging system must be technically defensible.
- **Adoptability & Operability (20%):** Whether Hackathon Raptors could realistically run the software. One-command startup, seeded data, documentation, migration paths, clean licensing, and self-hosting all matter.
- **Code Quality & Innovation (15%):** Code quality, maintainability, schema design, architecture, and the technical decisions that make the project stand out.

## Bonus Challenges

Optional bonus challenges are available:

| Bonus | Points |
|---|---|
| Normalization Proof | +5 |
| Pairwise Mode | +5 |
| Threat Model | +3 |
| API First | +3 |
| **Maximum bonus** | **+16** |

- **Normalization Proof (+5):** Implement cross-judge normalization and demonstrate its effect using the provided fixture data.
- **Pairwise Mode (+5):** Add pairwise project comparisons and recover rankings using a Bradley-Terry style estimator or another defensible method.
- **Threat Model (+3):** Publish a written threat model covering voting and submission abuse, including attacks such as Sybil voting, ballot stuffing, submission scraping, judge collusion, and deadline gaming.
- **API First (+3):** Expose every UI action through a documented API and publish an OpenAPI specification.

> One challenge done properly beats four unfinished features.

## Prizes

**₹250,000 Total Prize Pool**

| Prize | Amount |
|---|---|
| 1st Place — Grand Prize | ₹80,000 |
| 2nd Place — Runner-Up | ₹50,000 |
| 3rd Place | ₹35,000 |
| 4th Place | ₹20,000 |
| 5th Place | ₹15,000 |
| Best Judging Engine | ₹10,000 |
| Write Up Quest (4 winners × ₹10,000) | ₹40,000 |

The 1st-place project will be forked, self-hosted, and put into production for Hackathon Raptors events.

The winning team keeps ownership of its repository. Hackathon Raptors does not require an assignment, transfer, CLA, or exclusivity agreement.

## Rules

- Teams must contain 1–4 members.
- Solo participation is allowed.
- All project code must be written during the official 72-hour hackathon window.
- Planning, research, documentation reading, and AI prompt preparation are allowed before kickoff.
- No project code may be committed before kickoff.
- T1 must be completed for the project to be judged.
- The submitted GitHub repository must be public at submission time.
- The project must use an OSI-approved open-source license.
- The project must run locally without hosted-service dependencies.
- `docker compose up` must produce a working, seeded portal.
- The final project must be self-hostable and work without network connectivity.
- Existing projects cannot be submitted as-is.
- Renamed copies or rewrites of existing open-source hackathon platforms are not allowed.
- Tier claims must be honest and supported by the acceptance report.
- AI coding assistants are allowed.
- Frameworks, libraries, boilerplate generators, and development tools are allowed.
- The final software must be something the team can explain and defend.
- Any project that cannot be run and evaluated as required may not be considered for adoption.

## Important Dates

| Date | Event |
|---|---|
| August 24, 2026 | Registration opens |
| September 4, 2026 | Judging panel announced |
| September 21, 2026 | Team formation |
| September 24, 2026 | Full specification published |
| September 25, 2026, 18:00 UTC | Hackathon begins |
| September 28, 2026, 18:00 UTC | Code freeze and submission deadline |
| September 28 – October 8, 2026 | Judging window |
| October 5, 2026, 18:00 UTC | Write Up Quest closes |
| October 9, 2026 | Winners announced |

## About Hackathon Raptors

Hackathon Raptors is a Community Interest Company that runs online hackathons for working engineers and developers.

- 35+ hackathons run since 2023
- Participants from 85+ countries
- Roughly a dozen events run each year
- 300+ projects submitted in our last hackathon
- Events are designed around practical engineering challenges rather than purely conceptual ideas

> Dogfood is built around one simple proposition: **Build the platform that will judge you.**