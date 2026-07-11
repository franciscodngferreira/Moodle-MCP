# TODOS — deferred scope

Deferred from the CEO plan review (SELECTIVE EXPANSION). Not built now; captured so
the intent survives.

## Deferred features
- [ ] **Auto-flashcards** — tool that turns synced lecture notes into Q&A flashcards on
      demand from the local cache. Pure local, low risk. ~half day human / ~15 min CC.
- [ ] **Deadline calendar (.ics) export** — export exam/assignment deadlines as an .ics
      to import into a calendar. The "exam in Y days" math already works from
      `list_deadlines`; this just adds export. ~2h human / ~10 min CC.

## Known follow-ups / risks to revisit
- [ ] **OCR for scanned PDFs** — image-only slides yield no text. Out of scope now;
      revisit if a course's materials are mostly scans.
- [ ] **Cookie-session scraping fallback** — only build if ETH's `moodle_mobile_app`
      service turns out to be disabled (see PLAN.md auth Path B). Grayer on ToS.
- [ ] **Per-course taxonomy tuning** — if the classifier mislabels a specific course,
      add rules to `taxonomy.yaml`.
