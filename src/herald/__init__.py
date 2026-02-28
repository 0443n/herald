import os
import time
from enum import IntEnum
from pathlib import Path

BASE_DIR: Path = Path("/var/lib/herald")


class Urgency(IntEnum):
    LOW = 0
    NORMAL = 1
    CRITICAL = 2

    @classmethod
    def from_string(cls, s: str) -> "Urgency":
        try:
            return cls[s.upper()]
        except KeyError:
            raise ValueError(f"Invalid urgency: {s!r}") from None


def make_filename() -> str:
    """Generate a unique, chronologically sortable notification filename."""
    ts = time.time()
    rand = os.urandom(2).hex()
    return f"{ts:.6f}_{rand}.json"
