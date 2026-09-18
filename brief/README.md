# The brief

This folder is **the material I was given**, unedited. Everything else in the repo is what I produced from it.

| File | What it is |
|---|---|
| [`BRIEF.md`](BRIEF.md) | The engagement brief: the situation, the Director's question, what's in the raw dump, the known problems Ops admitted to, and the phase-by-phase deliverables |
| [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) | What Ops *says* the columns mean. The brief warns it is "a claim, not a fact" and that at least four statements are wrong — I found **11**, listed in [`../data_quality_report/DATA_QUALITY_REPORT.md`](../data_quality_report/DATA_QUALITY_REPORT.md) |
| [`VALIDATION_KEY.md`](VALIDATION_KEY.md) | The true values, taken from the source-of-truth before the data was deliberately degraded — the self-grading target. [`../pipeline/validate.py`](../pipeline/validate.py) encodes these as 93 hard checks, all passing |
| [`sql/01_schema.sql`](sql/01_schema.sql) | The supplied staging DDL (deliberately all-TEXT). My star schema is [`../sql/01_schema.sql`](../sql/01_schema.sql) |
| [`sql/02_questions.sql`](sql/02_questions.sql) | The 14 questions as handed over, unanswered. My answers are [`../sql/02_questions_answered.sql`](../sql/02_questions_answered.sql) |

The raw data files the brief describes are not in this repo — only the cleaned outputs in [`../clean/`](../clean/).

This is a training brief with a synthetic dataset, built so the defects are known in advance and the cleaning can be scored objectively. The work against it was done as if the engagement were real.
