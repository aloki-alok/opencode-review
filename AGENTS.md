# AGENTS.md

opencode-review is a GitHub Action that reviews pull requests and answers `/oc` questions with OpenCode. It is Python 3.11+, standard library only, and the model must stay read-only.

## Commands

- Test: `cd tests && python3 -m unittest -v` (131 tests, about 100 seconds, 2 skipped)
- Test one file: `cd tests && python3 -m unittest test_render -v`

Tests use a fake GitHub (`tests/fake_github.py`) and a fake OpenCode (`tests/fake_opencode.py`). They need no network and no key.

## Layout

- `action.yml`: composite action, inputs and the call to `src/main.py`.
- `src/main.py`: entry point that ties the passes together.
- `src/route.py`: decides review, ask or skip for each event.
- `src/diff.py`: builds the diff and drops lockfiles, translations, minified files and prose.
- `src/review.py`, `src/runner.py`, `src/extract.py`: run OpenCode, enforce budgets, parse its JSON.
- `src/budget.py`: the `turns:seconds` budgets.
- `src/render.py`, `src/github.py`: the comment text and the GitHub API calls.
- `src/install.py`: installs the pinned OpenCode version.
- `prompts/`: find, verify and ask prompts.
- `templates/`: `workflow.yml` and `guide.md` that users copy.
- `bench/`: replays real bug-introducing PRs to score a change. See `bench/README.md`.
- `docs/`: landing page for GitHub Pages.

## Rules

- Standard library only. Python is run with `-I`, so do not rely on the current directory for imports.
- The model only reads: read, glob, grep and list. Never add edit, shell, web or sub-agent tools.
- Never let a PR change the reviewer. Prompts and code come from the action's ref. The guide, `AGENTS.md` and `CLAUDE.md` come from the base branch. Project `opencode.json` and `.opencode/` are removed.
- Keep secrets away from OpenCode. It gets only the model key. The GitHub token never enters its environment or disk.
- Skip fork PRs, bots, drafts and Dependabot. Only owners, members and collaborators may use commands.
- Never post "Nothing blocking" for a run that failed.
- The workflow block in `README.md` and in `docs/index.html` must match `templates/workflow.yml` (`tests/test_docs.py` checks it). Edit all three together.
- Style: single quotes, 120 columns, ruff rules E, F, B, I (see `pyproject.toml`).
- Pin third-party actions in workflows to a full commit SHA.

## Before you open a PR

CI (`.github/workflows/ci.yml`) runs:

1. `cd tests && python3 -m unittest -v` on Python 3.11 and 3.13.
2. `actionlint` and `zizmor` on `action.yml`, `.github/workflows` and `templates/workflow.yml` (with `@v0` swapped for a SHA).

Run the unit tests locally. The live test (`tests/test_live.py`) runs only when `OPENCODE_LIVE_BIN` and `OPENCODE_LIVE_KEY` are set, and it costs money.
