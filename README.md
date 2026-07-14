# Moodle Study MCP

An [MCP](https://modelcontextprotocol.io) server that lets Claude read your ETH
Moodle courses so it can plan your exam prep. Ask Claude things like:

> "For Control Systems II, exam in 12 days — how many lectures, problem sets,
> quizzes and practice exams do I have, and what should I actually do?"

The server fetches, counts, and categorizes your course content. Claude does the
reasoning. Works for any Moodle site (defaults to ETH; set `MOODLE_URL` for others).

## What it gives Claude

| Tool | What it does |
|------|--------------|
| `list_courses` | Your enrolled courses |
| `get_course_overview` | Detected counts (lectures / problem sets / practice exams / quizzes) + the raw item list |
| `sync_course` | Downloads + text-extracts all materials into a local cache |
| `list_quizzes` | Every quiz + how many attempts you've made |
| `search_materials` | Full-text search across everything you've synced |
| `get_material` | The extracted text of one file, for Claude to read |

## Setup (ETH students)

Requires Python 3.10+.

```bash
git clone <this-repo> && cd Moodle-MCP
pip install -e .
```

### 1. Get your token (once)

ETH uses SSO, so you need a Moodle **web-service token** (a 32-character hex
string). The token is stored in your OS keyring (never in a file, never in git)
and is long-lived.

```bash
python -m moodle_mcp auth
```

This opens a browser; log in with SSO. At the end Moodle tries to hand the token
back via a `moodlemobile://token=...` redirect. Since no app is registered for
the `moodlemobile://` scheme, your browser shows an error — **"address invalid"**
(or *"Safari cannot open the page because the address is invalid"*). **That's
expected.** You just need to fish the `token=...` value out of that failed
redirect and paste it at the prompt.

Most browsers (Safari and Chrome included) **hide** the failed URL, so grab it
from DevTools instead:

- **Safari** — enable **Settings → Advanced → "Show features for web
  developers"**, then **Develop → Show Web Inspector** (`⌥⌘I`) → **Network** tab.
  Run the login, click the **`launch.php`** entry → **Response**, and search for
  `moodlemobile://token=`. Copy that whole value.
- **Chrome / Edge** — `Ctrl/⌘+Shift+I` → **Network** tab → run the login → open
  the **`launch.php`** response and find `token=`.

Paste that value at the `Paste the moodlemobile://token=... value here:` prompt
(the tool decodes it for you).

> **Non-ETH Moodle sites:** many expose the token directly under your profile →
> **Preferences → Security keys** (`<your-moodle>/user/managetoken.php`), listed
> as **"Moodle mobile web service"**. If it's there, skip the browser dance:
> `python -m moodle_mcp auth --token <token>`. Note: the **RSS** token on that
> page is *not* the right one, and ETH does not list the mobile token there.

Verify:

```bash
python -m moodle_mcp doctor
```

### 2. Register with Claude Code

```bash
claude mcp add moodle -- python -m moodle_mcp serve
```

Then in Claude: *"List my Moodle courses"*, or *"Give me a study overview of
Fluid Dynamics."*

## Other universities

```bash
export MOODLE_URL="https://moodle.your-uni.example"
python -m moodle_mcp auth
```

The classifier keywords (`taxonomy.yaml`) are tuned for German + English ETH
naming. Add your own patterns there if your course names differ.

## Privacy & security

- Your token is a password to your Moodle account. It lives only in your OS
  keyring. `.gitignore` excludes the cache and any token files.
- The local cache (`~/.moodle-mcp/`) holds copyrighted course material — it stays
  on your machine.
- Uses only Moodle's sanctioned mobile web-service API. No scraping.

## Development

```bash
pip install -e ".[dev]"
pytest
```
