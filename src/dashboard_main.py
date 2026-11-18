"""
Dashboard in un processo separato dal bot: `make dashboard` oppure `python src/dashboard_main.py`.

Usa lo STESSO database SQLite del bot (le scritture dei due processi sono arbitrate da SQLite: vedi
src/database.py). Per non avviarla due volte metti `DASHBOARD_IN_BOT=0` nel .env.
"""

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

import storage  # noqa: E402
from dashboard import ConfigError, DashboardConfig, DashboardServer  # noqa: E402
from database import Database, DatabaseError  # noqa: E402

log = logging.getLogger("dashboard")


async def main() -> None:
    config = DashboardConfig.from_env()
    db = await Database.open(storage.default_db_path())
    server = DashboardServer(db, config)
    try:
        await server.start()
        print(f"🖥️  Dashboard: {server.url}  (Ctrl+C per fermarla)")
        await asyncio.Event().wait()
    finally:
        await server.stop()
        await db.aclose()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except ConfigError as e:
        sys.exit(f"❌ {e}")
    except DatabaseError as e:
        sys.exit(f"❌ Database non utilizzabile: {e}")
    except OSError as e:
        sys.exit(f"❌ Impossibile avviare la dashboard (porta già in uso?): {e}")


if __name__ == "__main__":
    run()
