import os
import time

BASE_DIR = "/var/lib/herald"
VALID_URGENCY = {"low", "normal", "critical"}


def make_filename():
    """Generate a unique, chronologically sortable notification filename."""
    ts = time.time()
    rand = os.urandom(2).hex()
    return f"{ts:.6f}_{rand}.json"
