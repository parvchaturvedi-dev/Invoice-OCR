from __future__ import annotations

from waitress import serve

from .api import create_app
from .config import Settings


def main() -> None:
    serve(create_app(), host=Settings.HOST, port=Settings.PORT)


if __name__ == "__main__":
    main()
