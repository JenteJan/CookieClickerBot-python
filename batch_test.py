"""Launch a batch A/B test: N headless bots per group, one variable differs,
live aggregate dashboard (mean/median CPS and cookies per group).

    python batch_test.py        (or: ./run.sh --batch)

Because golden-cookie luck can't be seed-controlled, this samples many
independent runs and compares the distributions — the statistically sound way
to tell two settings apart. Analyse the finished logs with analyze_batch.py.
"""
from cookiebot.batch import batch_main

if __name__ == "__main__":
    batch_main()
