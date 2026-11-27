"""Shared pytest setup: make abcsim/ importable and expose one Repo B finder."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'abcsim'))
