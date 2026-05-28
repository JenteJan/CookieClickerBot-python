"""Entry point for the Cookie Clicker bot.

Usage:
    python cookieBot.py                  # Firefox (default)
    python cookieBot.py --browser chrome # Chrome
    python cookieBot.py --headless       # No window

Implementation lives in the ``cookiebot`` package.
"""
from cookiebot.runner import main

if __name__ == "__main__":
    main()
