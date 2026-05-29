"""Launch a synchronized A/B test of two profiles in side-by-side browser
windows, started at the same instant on a shared RNG seed.

    python ab_test.py        (or: ./run.sh  — see run.sh --ab)

Pick profiles A and B and a seed in the interactive menu; both run non-headless
with a shared dual dashboard, each writing a trial log you can compare with
compare_trials.py afterwards.
"""
from cookiebot.abtest import ab_main

if __name__ == "__main__":
    ab_main()
