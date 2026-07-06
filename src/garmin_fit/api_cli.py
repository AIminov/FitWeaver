"""Entry point: garmin-fit-api. Runs the Plan API with uvicorn.

Requires the [api] extra: pip install -e ".[api]"
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn/fastapi are not installed. Run: pip install -e \".[api]\"",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)

    from .api.app import create_app
    from .api.config import load_api_settings

    settings = load_api_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
