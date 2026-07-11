# Moodle Study MCP — Plan

An MCP server that lets Claude Code read your ETH Moodle courses so it can plan
your exam prep: "For course X, exam in Y days — how many lectures / problem sets
/ quizzes / practice exams do I have, what's relevant, and what should I do?"

The MCP does the fetching, counting, and categorizing. **Claude does the reasoning.**

## Approach (decided)

- **B: Study corpus.** Live Moodle Web Services + a local cache that downloads and
  text-extracts every resource so Claude can search and reason across a whole course.
- **Stack:** Python + the official `mcp` package (its `FastMCP` server class). NOT the
  separate legacy `fastmcp` PyPI package. Deps: `mcp`, `httpx`, `pypdf`, `keyring`;
  `sqlite3` (stdlib) for search.
- **Mode:** SELECTIVE EXPANSION — baseline bulletproof; quiz inventory + categorized
  overview + cross-course search are core. Flashcards + .ics deferred (see TODOS.md).
- **Module structure (locked):** 3 services + server + auth CLI (see below).

## Phase 0: GO/NO-GO spike — DONE ✅ (2026-07-12)

Result: **GO.** Host `moodle-app2.let.ethz.ch`, Moodle 5.1.5, userid 127221, 44 courses.
ALL needed functions available, **including `mod_quiz_*`** (the biggest risk). No fallback needed.
ETH uses **SSO** (edu-ID/Shibboleth), so `login/token.php` with username/password does NOT work —
token was captured via the mobile-app launch flow instead (see Auth).

## Auth (SSO — settled)

ETH is SSO, so there is no username/password token path. The token is captured ONCE via the
browser launch flow and reused (Moodle mobile tokens are long-lived):

1. Browser (already SSO-logged-in), open:
   `https://moodle-app2.let.ethz.ch/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=<n>&urlscheme=moodlemobile`
2. Capture the `moodlemobile://token=<base64>` redirect (DevTools Network log).
3. base64-decode → `signature:::token:::privatetoken`; the middle field is the wstoken.

**`auth.py` takes the captured token, NOT a password:** `python -m moodle_mcp auth --token <TOKEN>`
(or reads it from stdin). It validates via `core_webservice_get_site_info`, then stores the token
in the OS keyring (`keyring`). Never in code, never in git. If the token is ever invalidated,
re-run the browser capture and `auth` again.

## Modules

```
moodle_mcp/
  auth.py        # CLI: username+password -> token.php -> store token in keyring
  client.py      # MoodleClient: REST wrapper. ONE _call() chokepoint (see below)
  classify.py    # pure functions: (title, section, modtype) -> category  (taxonomy.yaml)
  cache.py       # download + text-extract + index.json + SQLite FTS5 index
  server.py      # FastMCP tools (thin; delegates to the three services)
```

### client.py — single chokepoint + typed errors
Every request goes through `MoodleClient._call(wsfunction, **params)`, which:
- appends `wstoken` + `moodlewsrestformat=json`,
- **parses the body for `exception`/`errorcode` even on HTTP 200** (Moodle's signature
  gotcha — it returns errors with a 200 status),
- raises typed exceptions, never bare `except`:
  - `MoodleAuthError` — `invalidtoken` → tell user to re-run `auth`
  - `MoodleFunctionUnavailable` — `accessexception` (function not in mobile allowlist)
  - `MoodleAPIError` — network/timeout (retry w/ backoff first) / malformed body

### Function discovery (decided: site_info at startup)
On startup call `core_webservice_get_site_info` once; cache `functions[]` + `userid`.
Before calling any optional function (esp. `mod_quiz_*`) check the cached list and
degrade gracefully — `get_course_overview` still returns even if quizzes are unavailable,
and tells you "quizzes unavailable on your instance."

## Tools (one method each)

| Tool | Returns |
|---|---|
| `list_courses()` | Enrolled courses (`core_enrol_get_users_courses` for cached userid) |
| `get_course_overview(course)` | **Money tool.** `lectures[] problem_sets[] quizzes[] practice_exams[] other[] deadlines[]`. Counts labelled **`(detected)`** + a **raw item list** with each item's guessed category + a low/med/high confidence, so Claude can eyeball and correct before reporting to you |
| `sync_course(course)` | Download + text-extract every downloadable file to cache; incremental |
| `list_quizzes(course)` | Moodle quizzes + your attempt status (`mod_quiz_*`, if available) |
| `search_materials(query, course="all")` | SQLite FTS5 search across cached text, spans all courses |
| `get_material(item)` | Extracted text of one resource so Claude can read + judge relevance |

## Cache layer (cache.py)

### Module-type branching (NOT everything is a downloadable file)
`core_course_get_contents` returns mixed item kinds. Branch on `modname`/type:
- **file / resource / folder** → download via `<host>/webservice/pluginfile.php/...?token=`
- **url (mod_url)** → external link; store the URL, DO NOT try to download
- **page / label** → inline HTML/text; extract text directly, no file download
- unknown → record title + type, skip download

Trying to download a `mod_url` as a file is a silent-failure trap — the branch prevents it.

### Incremental sync (decided: timemodified)
Store each file's `timemodified` (+ `filesize`) from `core_course_get_contents` in
`index.json`. Re-download only when `timemodified` increases. Prune cache entries whose
items no longer appear upstream (handles deletions). No hashing (would require downloading
to hash — defeats the point).

### Text extraction
`pypdf` (PDF), `python-docx` (docx), `html2text`/stdlib for pages. If a PDF is scanned
(0 chars extracted), set `text_extracted=false` on the item so Claude knows it can't read
it. OCR is out of scope (TODOS.md). Extraction failure must never crash a sync.

### Search index
On sync, insert extracted text into a local **SQLite FTS5** table (`sqlite3` stdlib).
`search_materials` queries the index (fast, ranked). No extra dependency.

## Architecture diagram

```
Claude Code
   | MCP (stdio)
   v
server.py (FastMCP tools)
   |-- auth: token from keyring
   |-- client.MoodleClient._call()  --> ETH Moodle /webservice/rest/server.php
   |       site_info (fn list + userid), enrol_get_users_courses,
   |       course_get_contents, mod_quiz_* (if available),
   |       calendar_get_action_events_by_timesort
   |       files: /webservice/pluginfile.php?token=...
   |-- classify.classify()  (taxonomy.yaml regex, DE+EN) -> category + confidence
   |-- cache: ~/.moodle-mcp/<course>/  files + <name>.txt + index.json + fts.db
   v
Claude reads overview (+raw items) + materials, builds your study plan.
```

## Test plan (pytest — tests written alongside each module)

Highest-priority ★★★ paths (pure-unit-testable, highest risk):
- `client._call`: 200+valid; **200+exception (invalidtoken → MoodleAuthError)**;
  **200+accessexception → MoodleFunctionUnavailable**; network error → retry → MoodleAPIError;
  malformed body → MoodleAPIError (no crash).
- `classify`: table tests per category, **German + English incl. umlauts**; unknown → "other"
  with raw title preserved.
- `cache.sync_course`: new file (download+extract+index); **unchanged (timemodified equal)
  → asserts NO download**; changed → re-download; deleted upstream → pruned; scanned PDF
  (0 chars) → `text_extracted=false`, no crash; **mod_url → stored as link, NOT downloaded**.
- `server.get_course_overview`: aggregation; **mod_quiz unavailable → overview still returns**.
- `auth`: good creds → token in keyring; ws disabled/bad creds → clear message, no traceback.

## Failure modes (each: test? error handling? silent?)

| Failure | Test | Error handling | User sees |
|---|---|---|---|
| Token expired mid-session | yes | MoodleAuthError | "re-run auth" (not silent) |
| mod_quiz blocked by mobile service | yes | site_info check + MoodleFunctionUnavailable | "quizzes unavailable" (not silent) |
| Scanned PDF, no text | yes | text_extracted=false flag | item marked unreadable (not silent) |
| mod_url treated as file | yes | module-type branch | link stored, no download attempt |
| Classifier miscategorizes | n/a | raw items + confidence exposed | Claude corrects (not silent) |
| ETH throttles / network drops | yes | retry+backoff → MoodleAPIError | "sync failed, retry" (not silent) |

No critical gaps: every failure above has a test AND error handling AND is visible.

## NOT in scope (deferred — see TODOS.md)
- Auto-flashcards; deadline .ics export; OCR for scanned PDFs; cookie-session scraping
  fallback (only if Phase 0 fails). Rationale in TODOS.md.

## What already exists
- Nothing local (greenfield). Reuse is library-level only: `mcp`/FastMCP, `httpx`,
  `pypdf`, `keyring`, `sqlite3`. Existing teacher-oriented Moodle MCPs (loyaniu/peancor)
  were reviewed and rejected as base — wrong use case (teacher, not student study).

## Build order
1. **Phase 0 spike** (token + site_info) — GO/NO-GO.
2. `auth` CLI.
3. `client.py` (`_call` + error parsing + site_info discovery) + tests.
4. `classify.py` + `taxonomy.yaml` + table tests.
5. `cache.py` (module-type branch, incremental, extraction, FTS5) + tests.
6. `server.py` tools wiring + integration tests.
7. Register in Claude Code (`claude mcp add`).

## Parallelization
Lane A: `auth` + `client.py` (shared: none after auth) → sequential, foundation.
Lane B: `classify.py` + `taxonomy.yaml` — **independent** (pure logic, no Moodle needed),
can build in parallel with Lane A.
Lane C: `cache.py` depends on `client.py` (Lane A). `server.py` depends on all.
Order: A + B in parallel → C → server.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean | Approach B, SELECTIVE EXPANSION, 2 deferred |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | 3 issues, all folded; 0 critical gaps |

**VERDICT:** CEO + ENG CLEARED — ready to implement (after Phase 0 GO/NO-GO spike).

NO UNRESOLVED DECISIONS
