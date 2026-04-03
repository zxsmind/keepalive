from __future__ import annotations

import logging
import sys


def configure_logging(level_name: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger("keepalive")
