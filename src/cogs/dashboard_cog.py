"""
Avvia la dashboard web dentro il processo del bot (stesso event loop, stesso database).

Si attiva SOLO se `DASHBOARD_PASSWORD` è impostata nel .env. Se preferisci la dashboard in un processo
separato (`python src/dashboard_main.py`) metti `DASHBOARD_IN_BOT=0`.
"""

import logging
import os

from discord.ext import commands

from dashboard import ConfigError, DashboardConfig, DashboardServer

log = logging.getLogger(__name__)

LOOPBACK = ("127.0.0.1", "localhost", "::1")


class DashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.server: DashboardServer | None = None

    async def cog_load(self) -> None:
        if os.getenv("DASHBOARD_IN_BOT", "1").strip().lower() in ("0", "false", "no"):
            log.info("Dashboard nel bot disattivata (DASHBOARD_IN_BOT=0).")
            return
        db = getattr(self.bot, "db", None)
        if db is None:
            log.warning("Dashboard non avviata: il database del bot non è disponibile.")
            return
        try:
            config = DashboardConfig.from_env()
        except ConfigError as e:
            log.info("Dashboard disattivata: %s", e)
            return

        if config.host not in LOOPBACK and not config.cookie_secure:
            log.warning(
                "La dashboard è raggiungibile da altri computer (%s) senza HTTPS: la password viaggerebbe in chiaro. "
                "Mettila dietro un reverse proxy HTTPS e imposta DASHBOARD_COOKIE_SECURE=1.", config.host)

        server = DashboardServer(db, config, bot=self.bot)
        try:
            await server.start()
        except OSError as e:
            # Porta occupata (es. già in esecuzione in un altro processo): il bot deve partire lo stesso
            log.error("Impossibile avviare la dashboard su %s:%s: %s", config.host, config.port, e)
            await server.stop()
            return
        self.server = server
        print(f"🖥️  Dashboard: {server.url}")

    async def cog_unload(self) -> None:
        if self.server is not None:
            await self.server.stop()
            self.server = None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DashboardCog(bot))
