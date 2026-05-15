from __future__ import annotations

from pathlib import Path

from dash import Dash

from . import backend
from .config import DEFAULT_WORKSPACE
from .callbacks import register_callbacks
from .ui.layout import create_layout

_ASSETS_FOLDER = str(Path(__file__).resolve().parents[1] / "assets")


def create_app() -> Dash:
    backend.ensure_workspace(DEFAULT_WORKSPACE)
    app = Dash(__name__, title="Job Search Workbench", suppress_callback_exceptions=True, assets_folder=_ASSETS_FOLDER)
    app.layout = create_layout()
    register_callbacks(app)
    return app

