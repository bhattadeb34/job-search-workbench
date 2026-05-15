import os
from pathlib import Path

# Load .env for local dev (does not override existing env vars)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from workbench.app import create_app  # noqa: E402

dash_app = create_app()
server = dash_app.server
app = dash_app

if __name__ == "__main__":
    dash_app.run(debug=False)
