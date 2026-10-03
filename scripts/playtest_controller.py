"""One-shot hook for VCMI_EXTERNAL_AI_SCRIPT; diagnostics are stored off stdout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playtesting.controller import main

if __name__ == "__main__":
    main()
