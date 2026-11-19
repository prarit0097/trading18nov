"""Thin executable entrypoint; all state is shared through --workspace."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from crypto_skills.cli import main
if __name__ == '__main__':
    raise SystemExit(main(['plan', *sys.argv[1:]]))
