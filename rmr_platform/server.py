from __future__ import annotations

import uvicorn

from .config import settings


def run() -> None:
    uvicorn.run("rmr_platform.main:app", host=settings.host, port=settings.port, reload=False, proxy_headers=True)


if __name__ == "__main__":
    run()
