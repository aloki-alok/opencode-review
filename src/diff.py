"""Build the diff the model reads, and count the changed code lines that size its budget."""

from __future__ import annotations

import subprocess

CODE = (
    'py',
    'js',
    'jsx',
    'mjs',
    'cjs',
    'ts',
    'tsx',
    'go',
    'rs',
    'java',
    'kt',
    'rb',
    'php',
    'cs',
    'c',
    'h',
    'cc',
    'cpp',
    'hpp',
    'swift',
    'scala',
    'sh',
)
# Generated files flood the diff and say nothing a reviewer can act on.
GENERATED = (
    'package-lock.json',
    'npm-shrinkwrap.json',
    'yarn.lock',
    'pnpm-lock.yaml',
    'bun.lock',
    'bun.lockb',
    'poetry.lock',
    'uv.lock',
    'Pipfile.lock',
    'Cargo.lock',
    'go.sum',
    'Gemfile.lock',
    'composer.lock',
    '*.po',
    '*.pot',
    '*.min.js',
    '*.min.css',
    '*.map',
)
# Prose carries none of the defects the reviewer looks for, and makes up most of a docs PR.
PROSE = ('*.md', '*.mdx', '*.txt', '*.rst')

CODE_SPECS = [f':(glob)**/*.{ext}' for ext in CODE]
SKIP_SPECS = [f':(exclude,glob)**/{name}' for name in GENERATED + PROSE]


def build(repo, merge_base, head):
    """Whole changed functions for code, plain hunks for the rest. The caller passes the merge base,
    so commits that landed on the base branch after the PR branched are not shown. Two trees are
    all it needs: it works on a depth-1 fetch."""
    rng = f'{merge_base}..{head}'
    code = _git(repo, 'diff', '--function-context', rng, '--', *CODE_SPECS, *SKIP_SPECS)
    rest = _git(repo, 'diff', rng, '--', '.', *[f':(exclude,glob)**/*.{e}' for e in CODE], *SKIP_SPECS)
    numstat = _git(repo, 'diff', '--numstat', rng, '--', *CODE_SPECS, *SKIP_SPECS)
    changed = sum(
        int(a) + int(d) for a, d, _ in (ln.split('\t', 2) for ln in numstat.splitlines()) if a != '-'
    )  # '-' is a binary file
    return code + rest, changed


def _git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True, text=True).stdout
