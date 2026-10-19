"""Stable repository root independent of the test file depth."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
