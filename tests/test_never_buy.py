"""Regression tests for the never-auto-buy upgrade filter.

The bot was observed auto-buying "Golden switch" and "Shimmering veil" — toggle
upgrades that trade away golden-cookie / clicking play for flat CpS, which this
bot doesn't want. They're caught by pool ('toggle'/'switch') OR by the [off]/[on]
name marker, so a single quirk can't let one through.

    .venv/bin/python tests/test_never_buy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cookiebot.config import is_never_buy_upgrade as f  # noqa: E401

_CASES = [
    # name, pool, expected
    ("Shimmering veil [off]", "", True),       # name marker alone
    ("Shimmering veil [on]", "toggle", True),
    ("Golden switch [off]", "toggle", True),
    ("Golden switch [on]", "", True),          # prefix fallback
    ("Milk selector", "toggle", True),         # cosmetic, pool-only signal
    ("Background selector", "toggle", True),
    ("Fancy sound selector", "switch", True),
    ("Lucky day", "", False),                  # real golden upgrade we DO want
    ("Get lucky", "", False),
    ("Plain donut", "cookie", False),          # flavored-cookie CpS upgrade
    ("Sugar crystal cookies", "", False),
    ("", "", False),
]


def test_never_buy_predicate():
    for name, pool, want in _CASES:
        assert f(name, pool) is want, (name, pool, want)


def test_pool_signal_independent_of_name():
    # Unknown future toggle with an innocuous name is still caught by pool.
    assert f("Some Brand New Thing", "toggle") is True
    assert f("Some Brand New Thing", "") is False


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run()
