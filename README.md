## Vibing — Autonomous AI Webmaster (GitHub Pages + GitHub Actions)

Vibing is a tiny, cheap, fully autonomous “AI webmaster.” On a schedule, an agent updates a static website by editing files in this repo and committing the changes. Each run saves a human‑readable reasoning log in `agent-reasoning/` for audit/history.

This project prioritizes:
- **All‑GitHub**: GitHub Pages for hosting + GitHub Actions for the agent.
- **Simple + cheap**: Python agent using OpenAI `gpt-4o-mini`.
- **Autonomy**: No human intervention; optionally use PRs with auto‑merge to keep a visible history.


### What it does
- Hosts a single static HTML page (`docs/index.html`) via GitHub Pages.
- On a schedule (hourly by default), the agent:
- Uses OpenAI (`gpt-5` by default) to incrementally beautify the editable section using only HTML/CSS.
  - Creativity controls: `TEMPERATURE` (default 0.6), and an internal iteration counter that nudges bigger changes over time.
  - Ensures exactly one `span#last-updated` is present and updates it to the current EST time.
  - Validates the snippet (no code fences/full-page tags/forbidden tags) before applying.
  - Commits changes to `main` and writes a detailed markdown log to `agent-reasoning/`.


### Architecture
- **Hosting**: GitHub Pages (source: `main`, folder: `docs/`).
- **Execution**: GitHub Actions scheduled workflow (cron). Minimum reliable cadence is ~5 minutes.
- **Agent**: Python script that:
  - Calls OpenAI `gpt-4o-mini`.
  - Implements two prompts/roles: `content creator` and `site editor`.
  - Edits `docs/index.html` within a constrained section.
  - Writes commit/PR via `GITHUB_TOKEN`.
  - Saves a detailed run log in `agent-reasoning/`.
- **Secrets**: `OPENAI_API_KEY` stored as a GitHub Repository Secret.


### Repository layout (planned)
```
.
├── docs/
│   └── index.html                  # Static site, edited by the agent
├── agent/
│   ├── prompts/
│   │   ├── content_creator.md      # Prompt for content generation
│   │   └── site_editor.md          # Prompt for safe/page-scoped editing
│   ├── run.py                      # Main entrypoint for the agent (Python)
│   └── config.yaml                 # Configs: mode, schedule docs, targets
├── agent-reasoning/
│   └── (created at runtime)        # One .md per run with logs
└── .github/
    └── workflows/
        └── agent.yml               # Scheduled workflow
```

Note: This README ships first. The directories/files above will be added in subsequent commits.


### Modes of operation
- **Direct push (no PR)**: Fastest, “hands off.” Uses `GITHUB_TOKEN` with `contents: write`.
- **PR flow (recommended for visibility)**: The workflow opens a PR per run; optional auto‑merge keeps it zero‑touch while preserving reviewable history.

Both modes are supported; the default can be set in config (to be introduced in `agent/config.yaml`).


### Schedule and timezones
- **Cadence**: hourly (`0 * * * *`).
- **Timezone**: Cron uses UTC. The agent will render the “last updated” timestamp on the page in EST for display.


### Content: scope and tone
- **No external data sources** in v1; content is purely model‑generated.
- **Tone**: Profanity is allowed by design for this project. Be aware that generated content may be offensive; this repository and site are public.
- **Length**: Prefer short, punchy updates (1–2 sentences) to keep diffs compact.


### Secrets and permissions
- Add a repository secret: `OPENAI_API_KEY`.
- The workflow uses the built‑in `GITHUB_TOKEN` with appropriate permissions:
  - `contents: write` (for commits)
  - `pull-requests: write` (if using PR mode)
- A separate GitHub PAT is optional and only needed if you prefer a dedicated bot user.


### Commit message format
`chore(agent): update content — run 2025-10-17 09:00 EST`


### Run logs (`agent-reasoning/`)
Each run writes a markdown file, e.g. `agent-reasoning/run-2025-10-17T14-00-00Z.md`, including:
- Prompts used (content + editor)
- Model + parameters
- Generated content
- File change summary (what section of `docs/index.html` changed)
- Timestamps (UTC + EST)
- Token usage and rough cost estimate
- Exit status


### Setup
1) **Create a public GitHub repo** and push this project.

2) **Add secrets**
   - Settings → Security → Secrets and variables → Actions → New repository secret:
     - Name: `OPENAI_API_KEY`
     - Value: your OpenAI key

3) **Enable GitHub Pages**
   - Settings → Pages → Build and deployment → Source: `Deploy from a branch`
   - Branch: `main` — Folder: `/docs`

4) **Set workflow permissions**
   - Settings → Actions → General → Workflow permissions:
     - Enable `Read and write permissions`
     - Check `Allow GitHub Actions to create and approve pull requests` (if using PR mode)

5) **Configure schedule/mode (coming in code)**
   - Defaults: 5‑minute cadence (testing), PR mode off unless configured.
   - You’ll be able to change cron and mode in `agent/config.yaml`.

6) **Visit your site** once `docs/index.html` exists and Pages is enabled:
   - `https://<your-username>.github.io/<your-repo>/`


### Local development (optional, once code lands)
#### Option A — Docker (recommended)
1) Ensure Docker is installed and running.
2) From the repo root, run:
   ```bash
   docker compose up --build
   ```
3) Visit `http://localhost:8080` to view the site. Edits to files under `docs/` hot‑reload.

To stop:
```bash
docker compose down
```

#### Option B — Simple local file preview
You can also open `docs/index.html` directly in a browser. Some features (like relative includes, if any later) may require a local server.

#### Option C — Python (will be used by the agent later)
- Requirements: Python 3.11+, `pipx` or `pip`.
- Once the agent is added:
  - `pip install -r agent/requirements.txt`
  - `python agent/run.py --once --mode=direct` (writes to `docs/index.html` and logs)


### Roadmap (near‑term)
- Scaffold `docs/index.html` with a clearly scoped, editable content area.
- Add prompts and Python agent (`agent/run.py`).
- Add scheduled workflow (`.github/workflows/agent.yml`).
- Implement config for mode (direct vs PR) and schedule.
- Record detailed run logs in `agent-reasoning/`.
- Switch cadence to hourly after initial testing.


### Notes
- This repository intentionally allows profane content. Consider adding disclaimers or access warnings if you later share the site broadly.
- No analytics in v1.


### License
Choose a license (e.g., MIT) and add it as `LICENSE`.


### GitHub Pages automation (gh CLI)
Prereqs:
- Install GitHub CLI and login: `gh auth login`
- Ensure you are in the repo root and have your changes committed

Run:
```bash
bash scripts/setup_github_pages.sh --public
```

Optional flags:
```bash
bash scripts/setup_github_pages.sh --repo yourname/vibing --public --force
```

What it does:
- Creates (or connects) the GitHub repo
- Pushes `main`
- Enables GitHub Pages from `main` → `/docs`
- Grants Actions write + PR approval permissions
- Outputs the Pages URL


### Deploy updates (CLI)
Commit and push site changes quickly:

```bash
bash scripts/deploy.sh --message "update homepage copy"
```

Options:
- `--all`: commit all changes in the repo, not just `docs/`
- `--message "..."`: custom commit message (default: `chore(site): deploy`)


### Local agent
Run the local agent to improve aesthetics and update the page:

```bash
python agents/run.py
```

Flags:
- `--dry-run`: compute but do not modify files

Outputs:
- Updates the content between `<!-- BEGIN_EDITABLE -->` and `<!-- END_EDITABLE -->` with a validated HTML/CSS snippet
- Replaces `#last-updated` text with an EST timestamp
- Writes a log to `agent-reasoning/run-<timestamp>.md` (includes mode, model, validation status, usage)
- Persists counter in `agents/state.json` for deterministic mode only


### LLM mode (OpenAI)
Install dependencies and set your API key:

```bash
pip install -r agents/requirements.txt
export OPENAI_API_KEY=sk-... # or use a manager like direnv
```

Run with the LLM (default mode):

```bash
python agents/run.py --mode llm --model gpt-5
```

Notes:
- The prompt lives at `agents/prompts/webmaster.md`.
- The agent requests an HTML/CSS snippet and validates it (no code fences/full-page tags/forbidden tags; must include a single `span#last-updated`). If invalid, it falls back to a safe minimal snippet.
- Tune creativity and size with env vars: `TEMPERATURE=0.6`.


### Automation via GitHub Actions
This repository includes `.github/workflows/agent.yml` which runs the agent hourly. Default model: `gpt-5`.

Configure secret:
- Go to Settings → Secrets and variables → Actions → New repository secret
- Name: `OPENAI_API_KEY`
- Value: your OpenAI key

What it does on each run:
1. Checks out the repo
2. Installs Python deps (`agents/requirements.txt`)
3. Runs `python agents/run.py --mode llm --model gpt-4o-mini`
4. Stages `docs/`, `agents/state.json`, `agent-reasoning/`
5. Commits with `chore(agent): update content — run <EST time>` if there are changes
6. Pushes to `main` (GitHub Pages deploys automatically from `/docs`)


