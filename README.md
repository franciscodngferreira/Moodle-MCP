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

ETH uses SSO, so you capture a token through the browser:

```bash
python -m moodle_mcp auth
```

It opens a browser, you log in with SSO, and it hands back a
`moodlemobile://token=...` value — paste that back into the prompt. The token is
stored in your OS keyring (never in a file, never in git) and is long-lived.

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
