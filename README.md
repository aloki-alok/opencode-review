# OpenCode code review

[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-OpenCode%20code%20review-blue?logo=github)](https://github.com/marketplace/actions/opencode-code-review)
[![Website](https://img.shields.io/badge/website-aloki--alok.github.io-blue)](https://aloki-alok.github.io/opencode-review/)

AI code review for your pull requests, and answers to `/oc` questions, run by
[OpenCode](https://opencode.ai) inside your own GitHub Actions with your own model key.

- **Reviews every PR.** One short comment with the defects the change introduces. A second pass
  tries to prove each one wrong before you see it. The comment is edited on every push, never
  duplicated.
- **Answers questions.** Comment `/oc why does this retry twice?` on any issue or PR and get an
  answer with `file:line` references.
- **Read-only.** The model can read your code and nothing else: no edits, no shell, no web.
- **Your runner, your model.** Any model OpenCode supports. OpenRouter by default. No service to
  sign up for, nothing stored anywhere.

Not affiliated with OpenCode or its authors.

## Set it up in two steps

**1. Add your model key as a secret.** In your repo: Settings, Secrets and variables, Actions,
New repository secret. Name it `OPENROUTER_API_KEY`. Get a key at
[openrouter.ai/keys](https://openrouter.ai/keys).

**2. Add this file** as `.github/workflows/opencode-review.yml`:

```yaml
name: OpenCode review

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  issue_comment: # zizmor: ignore[dangerous-triggers] members only, read-only model, see SECURITY.md
    types: [created]
  pull_request_review_comment:
    types: [created]

permissions: {}

concurrency:
  group: >-
    opencode-review-${{ github.event_name == 'pull_request'
    && format('pr-{0}', github.event.pull_request.number)
    || format('comment-{0}', github.event.comment.id) }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  opencode:
    if: github.event_name == 'pull_request' || startsWith(github.event.comment.body, '/oc')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: aloki-alok/opencode-review@v0
        with:
          model: openrouter/deepseek/deepseek-v4.1-flash
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
```

That's it. Open a PR and a review appears in a few minutes. :D

Two things to know:
- `/oc` commands start working once this file is on your default branch. GitHub runs comment
  triggers from there only. PR reviews work from the PR that adds the file.
- If your organization limits which actions may run (Settings, Actions, General), allow
  `aloki-alok/opencode-review@*`.

The same file lives in [`templates/workflow.yml`](templates/workflow.yml) with a comment on every
line. For the strongest supply-chain safety, pin `@v0` to a full commit SHA and let Dependabot
update it.

## Make it smarter about your repo (optional)

Copy [`templates/guide.md`](templates/guide.md) to `.github/opencode-review/guide.md` and fill in a
few lines: what the project is, where things live, and the rules that matter. The reviewer reads it
first, so it spends its time on your change instead of finding its way around. The guide is read
from the base branch, so a PR can't rewrite the rules for its own review.

## What you'll see

| Comment | Means |
|---|---|
| `Changes needed: 2 things. :/` | Defects found and double-checked. Each one names the file, the line and a fix. |
| `Nothing blocking found. :)` | The review finished and found nothing worth blocking on. |
| `... Stopped at the time limit, so it may have missed things.` | It ran out of time but kept what it found. |
| `... Stopped at the turn limit, so it may have missed things.` | It used all its turns but kept what it found. |
| `Review did not finish ... -_-` | It ran out of time with nothing to show. Comment `/oc review` to retry. |
| `Review failed for ...: <reason>. :(` | Something is set up wrong, for example a dead API key. The reason says what. |

At most 5 findings, under 150 words, no praise and no style nits. It never says "Nothing blocking"
for a run that failed.

## Commands

Comment on an issue or a pull request:

| Comment | Does |
|---|---|
| `/oc <question>` | Answers in the thread. On a PR it reads the PR's code and diff. |
| `/oc review` | On a PR, runs the review again and updates the review comment. |

Only repo owners, members and collaborators can use commands. Bots and PRs from forks are ignored.

## Settings

All optional except `model` and `api-key`.

| Input | Default | What it does |
|---|---|---|
| `model` | required | OpenCode model as `provider/model`. |
| `api-key` | required | Key for the model's provider. |
| `github-token` | `github.token` | Reads the PR and posts comments. |
| `trigger` | `/oc` | Command word. If you change it, change the `if:` in the workflow too. |
| `guide-path` | `.github/opencode-review/guide.md` | Repo guide, read from the base branch. |
| `max-findings` | `5` | Most findings in one comment. |
| `review-budget` | `auto` | `auto` sizes the review to the change: 90 s up to 20 changed code lines, else 240 s. Or `turns:seconds`. |
| `verify-budget` | `auto` | `turns:seconds` for the second pass. `auto` is 120 s. |
| `ask-budget` | `16:240` | `turns:seconds` for an answer. |
| `turn-p90` | `18` | Seconds one model turn takes at p90. Raise it for a slower model. |
| `allowed-associations` | `OWNER,MEMBER,COLLABORATOR` | Who may use commands. |
| `allow-public-self-hosted` | `false` | See [SECURITY.md](SECURITY.md). |
| `opencode-version` | `1.19.3` | OpenCode version to install. |
| `opencode-path` | | Use an `opencode` already on the runner instead of installing one. |

### Other models

Any provider OpenCode supports works. Pass its key and its model name:

```yaml
with:
  model: anthropic/claude-sonnet-5-5
  api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

A dead key is caught before the review starts only for OpenRouter. For other providers the error
from the provider shows up in the comment instead.

## Runners

GitHub-hosted Ubuntu runners work as they are. A self-hosted runner needs `python3` (3.11 or later),
`git` and `npm`, or set `opencode-path` to skip the install. No `gh` CLI is needed.

On a self-hosted runner, give reviews their own label (`runs-on: [self-hosted, ai-review]`) so they
don't wait behind builds. Every job gets its own fresh OpenCode folders, so jobs can run side by
side.

## How it works

1. The action fetches the PR's head, its base and their merge base, and builds the diff. Lockfiles,
   translations, minified files and prose (`.md`, `.mdx`, `.txt`, `.rst`) are left out. A PR that
   changes no code is skipped. Comment `/oc review` to review it anyway.
2. **Find pass:** OpenCode reads the diff, follows callers and types through the repo, and lists
   the defects it can back with a concrete scenario.
3. **Refute pass:** a second OpenCode run tries to prove each finding wrong. Only the ones that
   survive are posted.
4. The comment is written and edited in place. The job summary shows times, turns and the model.

If a pass hits its time limit, OpenCode is stopped and asked, in the same session, for what it
found so far. Work is not thrown away.

## Measuring changes

[`bench/`](bench) replays real bug-introducing PRs from a repo's own history, several times each,
and reports the catch rate, false alarms, timing and the spread between runs. Use it before
changing a prompt, a budget or a model. 17 public cases from httpx, click and flask are included.

## Security

The model only reads. The action's code and prompts never come from the PR. PRs from forks never
get your key. A PR can't add OpenCode config, plugins, or symlinks that reach outside the checkout.
Details in [SECURITY.md](SECURITY.md).

## License

MIT ;)
