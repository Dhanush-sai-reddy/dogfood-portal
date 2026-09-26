# 5-Minute Demo Video Script — Dogfood 2026

---

### [0:00 – 1:00] Introduction & Local Deployment
- **Visual:** Terminal showing `docker compose up --build`.
- **Narration:** "Welcome to Dogfood 2026. Our platform runs entirely offline with a single Docker command, seeding 41 projects, 30 judges, and complete reference data automatically without cloud dependencies."
- **Action:** Open browser to `http://localhost:8080/projects`. Show the Unstop-style hero banner and public gallery.

### [1:00 – 2:00] Participant Flow & Team Formation
- **Action:** Log in as a participant (using seeded test cookie).
- **Narration:** "Participants can register, create teams, and generate unique invite codes to collaborate with teammates."
- **Action:** Demonstrate `/teams/new` and team detail page with member lists and invite tokens. Show project submission (`/projects/new`) with backend deadline enforcement.

### [2:00 – 3:00] Judge Isolation & Pairwise Elo Judging
- **Action:** Log in as `judge_a`.
- **Narration:** "For judging, we support both traditional rubric scoring and modern Pairwise Bradley-Terry Elo comparisons to eliminate grading bias."
- **Action:** Show the `/judge` console and navigate to the new `/pairwise` arena showing side-by-side project comparisons.

### [3:00 – 4:00] Admin Settings & Configurable Judging
- **Action:** Log in as organizer/admin.
- **Narration:** "Organizers have complete control via `/admin/settings` to configure scoring methodologies, point pools, and mandatory comment requirements."
- **Action:** Show `/admin/audit` to demonstrate SQLite trigger-enforced immutable audit logs.

### [4:00 – 5:00] Acceptance Verification & Closing
- **Visual:** Terminal running `.venv/bin/python run.py .dogfood.toml`.
- **Narration:** "Our platform passes all organizer acceptance checks and unit tests cleanly with 100% correctness. Thank you!"
- **Action:** Show green acceptance output: `claimed T1 T2, verified T1 T2`.
