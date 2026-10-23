"""How many turns and seconds a pass gets."""

from __future__ import annotations

from typing import NamedTuple

# (changed code lines up to, seconds). A one-line fix must not walk to the big-PR cap. Above it, a
# 196-line PR whose turns ran about 25 s each still timed out at 180 s, so everything gets the max.
TIERS = ((20, 90),)
LARGEST = 240  # with a 60 s wrap-up and the second check, the worst case fits a 10 minute job
MIN_TURNS = 3


class Budget(NamedTuple):
    turns: int
    seconds: int


def find_budget(changed_lines, turn_p90):
    """Turns are set so that turns x p90 turn time fits the seconds: on a slow provider the step
    cap ends the run with an answer before the clock does."""
    seconds = next((s for limit, s in TIERS if changed_lines <= limit), LARGEST)
    return Budget(max(MIN_TURNS, int(seconds // turn_p90)), seconds)


def parse_budget(text):
    """`auto` -> None, `turns:seconds` -> Budget."""
    if text == 'auto':
        return None
    turns, _, seconds = text.partition(':')
    b = Budget(int(turns), int(seconds))
    if b.turns < 1 or b.seconds < 1:
        raise ValueError(f'budget must be positive: {text}')
    return b
