from __future__ import annotations

from pathlib import Path

from . import backend


APP_DIR = backend.APP_DIR
DEFAULT_WORKSPACE = backend.DEFAULT_WORKSPACE

STARTER_EXACT = """research engineer
mechanical engineer
materials engineer
data scientist
machine learning engineer"""

STARTER_TITLES = """research engineer
mechanical engineer
materials engineer
data scientist"""

STARTER_SKILLS = """Python
simulation
machine learning
materials
mechanical testing"""


def saved_keyword_text(workspace: Path = DEFAULT_WORKSPACE) -> str:
    keyword_file = workspace / "custom_keywords.txt"
    return keyword_file.read_text(encoding="utf-8") if keyword_file.exists() else ""

