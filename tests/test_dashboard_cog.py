"""Test dell'hosting della dashboard dentro il bot (cog) e del runner standalone."""

import socket
from types import SimpleNamespace

import aiohttp
import pytest

import cogs
from cogs import dashboard_cog
from database import Database


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(cogs, "BASE_DATA_DIR", tmp_path / "data")
    database = await Database.open(tmp_path / "t.sqlite3")
    yield database
    await database.aclose()


@pytest.fixture
def env(monkeypatch):
    for name in ("DASHBOARD_HOST", "DASHBOARD_PORT", "DASHBOARD_IN_BOT", "DASHBOARD_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    # vuoti ma presenti: load_dotenv() non sovrascrive, quindi il .env reale non filtra nel test
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("DASHBOARD_NO_PASSWORD", "")
    return monkeypatch


async def started(db, **bot_attrs):
    cog = dashboard_cog.DashboardCog(SimpleNamespace(db=db, **bot_attrs))
    await cog.cog_load()
    return cog


async def test_it_starts_only_when_a_password_is_set(db, env):
    cog = await started(db)
    assert cog.server is None                              # nessuna password: dashboard spenta, nessun errore

    env.setenv("DASHBOARD_PASSWORD", "corta")
    assert (await started(db)).server is None              # password troppo corta: rifiutata

    env.setenv("DASHBOARD_PASSWORD", "una password lunga")
    env.setenv("DASHBOARD_PORT", "0")
    cog = await started(db)
    port = cog.server.port
    try:
        assert port
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/api/session") as r:
                assert r.status == 200 and (await r.json())["authenticated"] is False
    finally:
        await cog.cog_unload()
    assert cog.server is None
    with pytest.raises(aiohttp.ClientConnectionError):     # fermata davvero
        async with aiohttp.ClientSession() as session:
            await session.get(f"http://127.0.0.1:{port}/api/session")


async def test_it_listens_on_localhost_by_default(db, env):
    env.setenv("DASHBOARD_PASSWORD", "una password lunga")
    env.setenv("DASHBOARD_PORT", "0")
    cog = await started(db)
    try:
        assert cog.server.config.host == "127.0.0.1" and cog.server.url.startswith("http://127.0.0.1:")
    finally:
        await cog.cog_unload()


async def test_it_can_be_disabled_for_the_standalone_setup(db, env):
    env.setenv("DASHBOARD_PASSWORD", "una password lunga")
    env.setenv("DASHBOARD_PORT", "0")
    env.setenv("DASHBOARD_IN_BOT", "0")
    assert (await started(db)).server is None


async def test_a_busy_port_does_not_stop_the_bot(db, env, caplog):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    env.setenv("DASHBOARD_PASSWORD", "una password lunga")
    env.setenv("DASHBOARD_PORT", str(blocker.getsockname()[1]))
    try:
        cog = await started(db)                           # non solleva
        assert cog.server is None and "Impossibile avviare la dashboard" in caplog.text
    finally:
        blocker.close()


async def test_without_a_database_it_stays_off(env):
    env.setenv("DASHBOARD_PASSWORD", "una password lunga")
    cog = dashboard_cog.DashboardCog(SimpleNamespace())
    await cog.cog_load()
    assert cog.server is None


async def test_warns_when_exposed_without_https(db, env, caplog):
    env.setenv("DASHBOARD_PASSWORD", "una password lunga")
    env.setenv("DASHBOARD_PORT", "0")
    env.setenv("DASHBOARD_HOST", "0.0.0.0")
    cog = await started(db)
    try:
        assert "senza HTTPS" in caplog.text
    finally:
        await cog.cog_unload()


def test_standalone_runner_reports_config_errors(env, capsys):
    import dashboard_main
    with pytest.raises(SystemExit) as exc:
        dashboard_main.run()
    assert "DASHBOARD_PASSWORD" in str(exc.value)


def test_no_password_mode_only_on_loopback_and_auto_session():
    from dashboard.app import ConfigError, DashboardConfig
    cfg = DashboardConfig.from_env({"DASHBOARD_NO_PASSWORD": "1"})
    assert cfg.no_password and cfg.password == ""
    with pytest.raises(ConfigError):
        DashboardConfig.from_env({"DASHBOARD_NO_PASSWORD": "1", "DASHBOARD_HOST": "0.0.0.0"})
    with pytest.raises(ConfigError):
        DashboardConfig.from_env({})
