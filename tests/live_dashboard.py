"""
Avvia una dashboard VERA su una porta libera, con dati di esempio, in un thread: serve ai test nel browser
(tests/test_dashboard_e2e.py) e a chi vuole provarla a mano:  python tests/live_dashboard.py
"""

import asyncio
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import cogs  # noqa: E402
import storage  # noqa: E402
from audio_samples import MP3, wav_bytes, write, zip_bytes  # noqa: E402
from dashboard import DashboardConfig, DashboardServer  # noqa: E402
from database import Database  # noqa: E402

PASSWORD = "password-di-prova"


class LiveDashboard:
    def __init__(self, seed: bool = True):
        self.seed = seed
        self.url = ""
        self.tmp = Path(tempfile.mkdtemp(prefix="driftbot-live-"))
        self._ready, self._stop = threading.Event(), threading.Event()
        self._loop = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.db = None

    async def _main(self):
        cogs.BASE_DATA_DIR = self.tmp / "data"
        storage.RVC_MODELS_DIR = self.tmp / "models"
        self.db = await Database.open(self.tmp / "live.sqlite3")
        if self.seed:
            await seed_data(self.db, self.tmp)
        server = DashboardServer(self.db, DashboardConfig(password=PASSWORD, port=0, fail_delay=0))
        await server.start()
        self.url = f"http://127.0.0.1:{server.port}"
        self._ready.set()
        while not self._stop.is_set():
            await asyncio.sleep(0.05)
        await server.stop()
        await self.db.aclose()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        self._loop.run_until_complete(self._main())

    def start(self):
        self._thread.start()
        assert self._ready.wait(15), "la dashboard non è partita"
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(10)

    def run(self, coro):
        """Esegue una coroutine nel loop della dashboard (per leggere/scrivere il database dai test)."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(10)


async def seed_data(db, tmp: Path):
    await storage.sync_guilds(db, [(111, "Casa di Gigi", None, 18), (222, "Ufficio Gaming", None, 42), (333, "Server dismesso", None, 5)])
    await storage.mark_guild_left(db, 333)
    up = tmp / "seed"
    for guild, name, data in ((0, "Airhorn", MP3), (0, "Sad trombone", wav_bytes(2)), (111, "Applauso", wav_bytes(1.5)),
                              (111, "Rullo di tamburi", wav_bytes(3)), (222, "Vittoria", MP3)):
        await storage.add_sound(db, guild, name, write(up / f"{name}.bin", data), actor="dashboard")
    await storage.add_voice(db, 111, "Gigi", write(up / "gigi.wav", wav_bytes(12)))
    await storage.add_voice(db, 111, "Marta", write(up / "marta.wav", wav_bytes(8)))
    await storage.add_voice(db, 222, "Capo Ufficio", write(up / "capo.wav", wav_bytes(20)))
    await storage.add_rvc_model(db, "Hatsune Miku", write(up / "miku.zip", zip_bytes({"miku.pth": b"x" * 500_000, "miku.index": b"i" * 4000})), "miku.zip",
                                description="Voce sintetica giapponese")
    await storage.add_rvc_model(db, "Narratore profondo", write(up / "narr.pth", b"p" * 20000), "narr.pth", guild_ids=[111])
    spento = await storage.add_rvc_model(db, "Test vecchio", write(up / "old.pth", b"p" * 3000), "old.pth")
    await storage.update_rvc_model(db, spento["id"], enabled=False)


if __name__ == "__main__":
    live = LiveDashboard().start()
    print(f"Dashboard di prova: {live.url}   password: {PASSWORD}   (Ctrl+C per fermare)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        live.stop()
