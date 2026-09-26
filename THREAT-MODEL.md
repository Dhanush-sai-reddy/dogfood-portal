# Threat Model & Security Architecture — Dogfood 2026

This document details the security model, trust boundaries, and threat mitigations implemented in the Dogfood 2026 hackathon platform.

---

## 1. Trust Boundaries & Roles

The system recognizes four distinct trust tiers:
1. **Participant:** Can submit projects, edit draft submissions, and form/join teams via invite codes. Cannot view submissions before the deadline or access peer submissions/scores.
2. **Judge:** Can view assigned projects and submit rubric or pairwise scores. Strictly bounded by query-level isolation (cannot view peer scores or unassigned projects).
3. **Organizer:** Can configure judging scales, manage event metadata, and export sanitized CSV data.
4. **Admin:** Full system privileges, audit log inspection, and schema management.

---

## 2. Threat Analysis & Mitigations

### Threat 1: Score Tampering & Audit Evasion
* **Attack Vector:** An insider or compromised admin attempts to modify historical scores or delete audit trail entries directly in the SQLite database file.
* **Mitigation:** **Database-Enforced Immutability.** We enforce strict `AFTER UPDATE` and `AFTER DELETE` triggers on the `audit_log` and `scores` tables. Any direct SQL attempt to mutate or delete historical audit rows raises an explicit SQL constraint failure, rejecting the transaction at the storage engine level.

### Threat 2: Cross-Judge Score Leakage (Data Confidentiality)
* **Attack Vector:** A judge attempts to inspect what score Judge B gave to a competing team to calibrate their own score or bias results.
* **Mitigation:** **Query-Level SQL Isolation.** Judge authorization is not hidden via frontend CSS or conditional template rendering. The FastAPI router inspects the judge's session ID and explicitly filters database queries (`Score.judge_id == judge.id`), making peer score leakage structurally impossible at the SQL level.

### Threat 3: Session Hijacking & Token Bruteforcing
* **Attack Vector:** An attacker attempts to guess session tokens or steal cookies to impersonate organizers or judges.
* **Mitigation:** **Opaque Cryptographic Tokens & Hashing.** Sessions use high-entropy cryptographic tokens stored securely as hashed lookup values in the database, delivered via secure HttpOnly, SameSite cookies with constant-time token verification.

### Threat 4: Deadline Bypass & Post-Deadline Submissions
* **Attack Vector:** A participant attempts to modify a submission after the 72-hour hackathon deadline by forging API requests.
* **Mitigation:** **Server-Side UTC Datetime Enforcement.** Both FastAPI form handlers and JSON endpoints validate `datetime.now(timezone.utc)` against `Event.submissions_close` before committing any mutation.

### Threat 5: Offline Container Supply Chain Attacks
* **Attack Vector:** A compromised PyPI package or malicious upstream CDN script injects code during container build.
* **Mitigation:** **100% Offline Hash-Pinned Build.** The Dockerfile utilizes `--require-hashes` with universal wheel pins (`--only-binary=:all:`), vendor-bundled HTMX 2.0.10, and zero external runtime network requests.
