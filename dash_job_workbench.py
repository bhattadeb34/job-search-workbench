import os

from workbench.app import create_app


app = create_app()
server = app.server


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", "8050")))
