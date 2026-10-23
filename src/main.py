"""Entry point of the action: route the event, fetch the code, run OpenCode, post the result.
Advisory: it always exits 0, and says in the log and the comment why when it could not finish."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I does not add the script dir

import install  # noqa: E402
import review  # noqa: E402
import runner  # noqa: E402
from budget import parse_budget  # noqa: E402
from diff import build  # noqa: E402
from github import GitHub, key_status  # noqa: E402
from render import MARKER, Outcome, render  # noqa: E402
from route import Settings, route  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OPENCODE = '1.19.3'  # the version the bench numbers were measured on
ANSWER_MARKER = '<!-- opencode-review:answer -->'
OPENROUTER_KEY_URL = 'https://openrouter.ai/api/v1/key'


class Log:
    def __init__(self, secrets):
        self.secrets = [s for s in secrets if s]

    def mask(self, text):
        for s in self.secrets:
            text = text.replace(s, '***')
        return re.sub(r'sk-[A-Za-z0-9_-]{8,}', 'sk-***', text)

    def __call__(self, text):
        print(self.mask(str(text)), flush=True)


def _cancelled(signum, frame):
    # GitHub cancels a job with SIGINT then SIGTERM. OpenCode runs in its own process group, so
    # stop it here or it keeps running, holding the key, on a self-hosted runner.
    runner.stop_all()
    sys.exit(0)


def main(env):
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _cancelled)
    # git sees the token base64-encoded, and a failed git command prints its argv.
    auth = base64.b64encode(f'x-access-token:{env.get("OC_GITHUB_TOKEN", "")}'.encode()).decode()
    env = {**env, 'OC_GIT_AUTH': auth}
    log = Log([env.get('OC_API_KEY'), env.get('OC_GITHUB_TOKEN'), auth])
    try:
        _main(env, log)
    except Exception:  # advisory: a crash must not fail the PR's checks
        log(traceback.format_exc())
    return 0


def _main(env, log):
    key = env.get('OC_API_KEY', '')
    print(f'::add-mask::{env["OC_GIT_AUTH"]}', flush=True)
    if key:
        print(f'::add-mask::{key}', flush=True)
    else:
        return _skip(env, log, 'no API key (Dependabot and fork PRs get no secrets)')
    event_name = env['GITHUB_EVENT_NAME']
    event = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())
    settings = Settings(
        trigger=env.get('OC_TRIGGER') or '/oc',
        associations=tuple(a.strip() for a in env.get('OC_ASSOCIATIONS', '').split(',') if a.strip())
        or Settings.associations,
        allow_public_self_hosted=env.get('OC_ALLOW_PUBLIC_SELF_HOSTED') == 'true',
    )
    gh = GitHub(env.get('GITHUB_API_URL', 'https://api.github.com'), env['GITHUB_REPOSITORY'], env['OC_GITHUB_TOKEN'])

    pr = event.get('pull_request')
    if event_name == 'issue_comment' and 'pull_request' in event.get('issue', {}):
        words = event['comment']['body'].split(None, 1)
        pr = gh.pull(event['issue']['number']) if words and words[0] == settings.trigger else None
    job = route(event_name, event, pr, settings, env.get('RUNNER_ENVIRONMENT', ''))
    if job.mode == 'skip':
        return _skip(env, log, job.reason)
    log(f'mode: {job.mode}, #{job.number}')
    if job.comment_id:
        gh.react(job.comment_id, job.comment_kind)
    if job.is_pr and event_name != 'pull_request':
        pr = gh.pull(job.number)  # a comment reviews the PR as it is now

    work = Path(tempfile.mkdtemp(prefix='opencode-review-', dir=env.get('RUNNER_TEMP')))
    try:
        _run_job(env, log, gh, job, event, pr, key, work)
    except Exception:
        # Say so on the PR: silence would leave an older "Nothing blocking" standing.
        log(traceback.format_exc())
        _post_failure(log, gh, job, pr, 'something went wrong, see the job log')
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _post_failure(log, gh, job, pr, reason):
    try:
        if job.mode == 'review':
            gh.upsert_comment(
                job.number, MARKER, render(Outcome(pr['head']['sha'], 'failed', None, 'skipped', None, 5, reason))
            )
        else:
            gh.reply(job.number, job.comment_id, job.comment_kind, _answer_body(f'I could not answer: {reason}.'))
    except Exception:
        log(traceback.format_exc())


def _run_job(env, log, gh, job, event, pr, key, work):
    code = work / 'code'
    if job.is_pr:
        head, base = pr['head']['sha'], pr['base']['sha']
        merge_base = gh.call('GET', f'/compare/{base}...{head}')['merge_base_commit']['sha']
        _fetch(env, code, [head, base, merge_base], head)
        review.sanitize(code, base)
    else:
        head = base = merge_base = ''
        _fetch(env, code, [f'refs/heads/{event["repository"]["default_branch"]}'], 'FETCH_HEAD')
        review.sanitize(code, None)
    (code / '.review').mkdir()

    failure = ''
    try:
        opencode = env.get('OC_OPENCODE') or install.install(
            env.get('OC_OPENCODE_VERSION') or DEFAULT_OPENCODE, Path(env['RUNNER_TEMP'], 'opencode-review-bin')
        )
        log(f'opencode: {opencode} ({_version(opencode, work)})')
    except install.InstallError as e:
        failure = log.mask(f'could not install OpenCode ({e})')
        log(failure)
    failure = failure or _key_failure(env, log, key)
    model = review.Model(
        opencode if not failure else '',
        env['OC_MODEL'],
        key,
        float(env.get('OC_TURN_P90') or 18),
        int(env.get('OC_WRAP_SECONDS') or 60),
    )
    ctx = dict(env=env, log=log, gh=gh, job=job, code=code, work=work, model=model)
    if job.mode == 'review':
        _review(ctx, pr, head, base, merge_base, failure)
    else:
        _ask(ctx, base, merge_base, head, failure)


def _skip(env, log, reason):
    log(f'skip: {reason}')
    _summary(env, f'opencode-review: skipped ({reason})')


def _fetch(env, code, refs, checkout):
    """Depth-1 fetch of exactly the commits needed. The token goes in per command, never into
    .git/config, because the model can read every file in the checkout."""
    url = f'{env.get("GITHUB_SERVER_URL", "https://github.com")}/{env["GITHUB_REPOSITORY"]}.git'
    auth = env['OC_GIT_AUTH']
    code.mkdir(parents=True)
    review.git(code, 'init', '-q')
    subprocess.run(
        [
            'git',
            '-C',
            str(code),
            '-c',
            f'http.extraheader=AUTHORIZATION: basic {auth}',
            'fetch',
            '-q',
            '--no-tags',
            '--depth=1',
            url,
            *dict.fromkeys(refs),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # Symlinks become plain files holding their target: a PR can't link outside the checkout.
    review.git(code, '-c', 'core.symlinks=false', 'checkout', '-q', '--detach', checkout)


def _version(opencode, work):
    home = work / 'version-home'  # OpenCode writes to ~/.config even for --version
    home.mkdir(exist_ok=True)
    try:
        r = subprocess.run(
            [opencode, '--version'],
            capture_output=True,
            text=True,
            timeout=30,
            env={'PATH': os.environ.get('PATH', ''), 'HOME': str(home)},
        )
        return r.stdout.strip() or 'version unknown'
    except (OSError, subprocess.TimeoutExpired):
        return 'version unknown'


def _key_failure(env, log, key):
    """A reason string if the provider rejects the key, else ''. Only OpenRouter has a key endpoint."""
    if not env['OC_MODEL'].startswith('openrouter/'):
        return ''
    status = key_status(env.get('OC_KEY_CHECK_URL') or OPENROUTER_KEY_URL, key)
    log(f'key check: HTTP {status}')
    return f'the model API key was rejected (HTTP {status})' if status in (401, 403) else ''


def _review(ctx, pr, head, base, merge_base, failure):
    env, log, gh, job = ctx['env'], ctx['log'], ctx['gh'], ctx['job']
    if env['GITHUB_EVENT_NAME'] == 'pull_request' and not build(ctx['code'], merge_base, head)[1]:
        return _skip(env, log, 'no code changed (comment /oc review to run it anyway)')
    max_findings = int(env.get('OC_MAX_FINDINGS') or 5)
    if failure:
        outcome = Outcome(head, 'failed', None, 'skipped', None, max_findings, failure)
    else:
        guide = _guide(ctx, base)
        r = review.review(
            ctx['model'],
            ctx['code'],
            ctx['work'],
            merge_base,
            head,
            f'# {pr["title"]}\n\n{pr.get("body") or ""}\n',
            guide,
            env.get('OC_REVIEW_BUDGET') or 'auto',
            max_findings,
            log,
            env.get('OC_VERIFY_BUDGET') or 'auto',
        )
        outcome = r.outcome
        outcome.reason = log.mask(outcome.reason)
    body = render(outcome)
    log(body)
    if gh.pull(job.number)['head']['sha'] != head:
        log('not posting: the PR has a newer commit, whose run posts instead')
        return
    gh.upsert_comment(job.number, MARKER, body)
    _summary(
        env,
        f'opencode-review: review of {head[:9]}, find {outcome.find}, verify {outcome.verify}, '
        f'model {env["OC_MODEL"]}\n\n{body}',
    )


def _guide(ctx, ref):
    """The repo guide at `ref`: the PR's base, or the default branch for an issue. Never the PR's copy."""
    path = ctx['env'].get('OC_GUIDE_PATH') or '.github/opencode-review/guide.md'
    guide = review.guide_at(ctx['code'], ref, path)
    ctx['log'](f'guide: {path} ({len(guide)} chars)' if guide else f'guide: none at {path}')
    return guide


def _ask(ctx, base, merge_base, head, failure):
    env, log, gh, job, code = ctx['env'], ctx['log'], ctx['gh'], ctx['job'], ctx['code']
    if failure:
        answer = f'I could not answer: {failure}.'
    else:
        issue = gh.issue(job.number)
        thread = [f'# {issue["title"]}\n\n{issue.get("body") or ""}\n\n## Recent comments']
        recent = [c for c in gh.comments(job.number) if not c['body'].startswith('<!-- opencode-review')][-20:]
        thread += [f'\n**{c["user"]["login"]}:** {c["body"][:2000]}' for c in recent]
        (code / '.review/thread.md').write_text('\n'.join(thread) + '\n')
        (code / '.review/question.md').write_text(job.question + '\n')
        if job.is_pr:
            (code / '.review/diff.patch').write_text(build(code, merge_base, head)[0])
        budget = parse_budget(env.get('OC_ASK_BUDGET') or '16:240')
        r = review.one_pass(
            ctx['model'],
            code,
            ctx['work'],
            'ask',
            review.prompt('ask.md', budget.turns, _guide(ctx, base or 'HEAD')),
            budget,
            None,
        )
        log(f'ask pass: {r.status}, {r.turns} turns, {r.seconds} s')
        answer = r.answer or 'I could not finish an answer in time. :( Try a narrower question.'
    gh.reply(job.number, job.comment_id, job.comment_kind, _answer_body(log.mask(answer)))
    _summary(env, f'opencode-review: answered on #{job.number}, model {env["OC_MODEL"]}')


def _answer_body(answer):
    return f'{ANSWER_MARKER}\n{answer}\n\n<sub>OpenCode answer, read-only, advisory. :)</sub>'


def _summary(env, text):
    path = env.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a') as f:
            f.write(text + '\n')


if __name__ == '__main__':
    sys.exit(main(os.environ))
