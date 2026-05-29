"""One-shot Cookie Clicker achievements the bot can help unlock.

Each entry has a JS snippet executed in the page context. The runner checks
``Game.Achievements[name].won`` before firing so re-running an enabled
achievement on a save that already owns it is a no-op.

Several of these are awarded by the game inside an *event handler* (the ticker
click handler) or a *prompt button* (the bakery-name dialog), not by the
underlying setter function — so the snippet calls ``Game.Win(name)`` directly,
which is idempotent and is exactly what those handlers do. Triggers verified
against the live main.js.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Achievement:
    name: str            # exact in-game name (key into Game.Achievements)
    js: str              # snippet to fire it
    note: str            # one-line description for menu / log
    shadow: bool = False  # wiki's shadow flag (doesn't count toward milk)


# No CPS or gameplay cost. Cosmetic side effects are fine (e.g. bakery rename).
SAFE: list[Achievement] = [
    Achievement(
        name="Tiny cookie",
        js="if (typeof Game.tinyCookie === 'function') { Game.tinyCookie(); } else { Game.Win('Tiny cookie'); }",
        note="Click the tiny cookie icon in Stats.",
    ),
    Achievement(
        name="Here you go",
        js="Game.Win('Here you go');",
        note="The empty achievement slot.",
    ),
    Achievement(
        name="Olden days",
        js="Game.Win('Olden days');",
        note="Click the forgotten madeleine in the Info pane.",
    ),
    Achievement(
        name="Tabloid addiction",
        # The 50-ticker-clicks achievement is awarded in the tickerL click
        # *event handler* (it bumps Game.TickerClicks then Game.Win), NOT by
        # TickerDraw — so the old TickerDraw loop did nothing. Bump the counter
        # and award directly, exactly what 50 real clicks would do.
        js="Game.TickerClicks = Math.max(Game.TickerClicks, 50); Game.Win('Tabloid addiction');",
        note="Equivalent to clicking the news ticker 50 times.",
    ),
    Achievement(
        name="Stifling the press",
        # Normally awarded by clicking the ticker while the window is narrow
        # enough to compress the ticker (windowW < tickerTooNarrow) — not
        # reliably reproducible from script, so award it directly.
        js="Game.Win('Stifling the press');",
        note="Click the ticker in a very narrow window (force-won here).",
    ),
    Achievement(
        name="Uncanny clicker",
        js=(
            "var _ucH = setInterval(function() { Game.ClickCookie(); }, 50);"
            " setTimeout(function() { clearInterval(_ucH); }, 3000);"
        ),
        note="Sustained ~20 clicks/sec for 3 s.",
    ),
    Achievement(
        name="What's in a name",
        # bakeryNameSet only sets the name; "What's in a name" is awarded by the
        # name prompt's Confirm button via Game.Win. So set a name (cosmetic)
        # AND award directly — together that's exactly what naming the bakery does.
        js="if (!Game.bakeryName || Game.bakeryName === 'Test') Game.bakeryNameSet('CookieBot'); Game.Win(\"What's in a name\");",
        note="Names the bakery (awards the naming achievement).",
    ),
    Achievement(
        name="Cookie-dunker",
        js="Game.Win('Cookie-dunker');",
        note="Force-wins (the in-game trigger needs a window resize).",
    ),
]


# Permanent CPS or save side effects — never fired by default.
RISKY: list[Achievement] = [
    Achievement(
        name="God complex",
        js=(
            # Capture the original name, rename to 'Orteil' (the achievement check
            # fires synchronously inside bakeryNameSet), then restore so the
            # permanent -1% CPS debuff associated with the 'Orteil' name doesn't
            # stick. Restore to a safe non-trigger name if the original was empty
            # or itself 'Orteil'.
            "var _old = Game.bakeryName;"
            " Game.bakeryNameSet('Orteil');"
            " Game.bakeryNameSet((_old && _old !== 'Orteil') ? _old : 'CookieBot');"
        ),
        note="Renames bakery to 'Orteil' to trigger, then restores your previous name (avoids the -1% CPS debuff).",
        shadow=True,
    ),
    Achievement(
        name="Just wrong",
        js="if (Game.Objects['Grandma'] && Game.Objects['Grandma'].amount > 0) { Game.Objects['Grandma'].sell(1); }",
        note="Sell one Grandma. Costs ~1 grandma's CPS, refunds ~25%.",
    ),
]


ALL: list[Achievement] = SAFE + RISKY
