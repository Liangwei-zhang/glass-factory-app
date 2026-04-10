from __future__ import annotations

import asyncio

from loguru import logger

from apps.scheduler.main import start_scheduler


async def _run() -> None:
    scheduler = await start_scheduler()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        logger.info("scheduler shutting down")
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
