"""Il bot vero (tutti i cog caricati da main.py) con la dashboard dentro: un solo database condiviso."""

import aiohttp
import pytest

import storage
from audio_samples import wav_bytes, zip_bytes
from fakes import FakeGuild, FakeInteraction, FakeSource, make_channel

PASSWORD = "una password lunga"


@pytest.fixture
async def bot(isolated_data, monkeypatch):
    import main

    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    monkeypatch.setenv("DASHBOARD_NO_PASSWORD", "")   # il .env reale non deve filtrare nel test
    monkeypatch.setenv("DASHBOARD_PORT", "0")
    bot = main.MyBot()

    async def fake_sync():
        return []

    monkeypatch.setattr(bot.tree, "sync", fake_sync)       # niente chiamate a Discord
    await bot.setup_hook()                                  # apre il database, importa i JSON, carica TUTTI i cog
    yield bot
    await bot.close()


class Dashboard:
    def __init__(self, bot, session, csrf):
        self.base = f"http://127.0.0.1:{bot.get_cog('DashboardCog').server.port}"
        self.session, self.csrf = session, csrf

    def headers(self):
        return {"X-CSRF-Token": self.csrf, "Origin": self.base}

    async def upload(self, path, data, filename, **fields):
        form = aiohttp.FormData()
        for key, value in fields.items():
            form.add_field(key, value)
        form.add_field("file", data, filename=filename)
        async with self.session.post(self.base + path, data=form, headers=self.headers()) as r:
            return r.status, await r.json()


@pytest.fixture
async def dash(bot):
    base = f"http://127.0.0.1:{bot.get_cog('DashboardCog').server.port}"
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        async with session.post(base + "/api/login", json={"password": PASSWORD}, headers={"Origin": base}) as r:
            assert r.status == 200
            csrf = (await r.json())["csrf"]
        yield Dashboard(bot, session, csrf)


async def test_every_cog_and_the_dashboard_load_with_the_bots_database(bot):
    assert bot.db is not None and bot.get_cog("DashboardCog").server is not None
    for name in ("Soundboards", "Create_Speaker", "TTSCog", "AICover", "Music"):
        assert bot.get_cog(name) is not None, name


async def test_a_sound_uploaded_in_the_dashboard_shows_up_and_plays_in_discord(bot, dash, monkeypatch):
    await storage.sync_guilds(bot.db, [(7, "Casa", None, 3)])
    status, data = await dash.upload("/api/sounds", wav_bytes(1), "gong.wav", name="Gong", scope="global")
    assert status == 201

    soundboard = bot.get_cog("Soundboards")
    guild = FakeGuild(7)
    channel = make_channel(guild)
    it = FakeInteraction(guild, channel)
    choices = await soundboard.sound_autocomplete(it, "go")
    assert [(c.name, c.value) for c in choices] == [("🌐 Gong", str(data["sound"]["id"]))]

    monkeypatch.setattr("discord.FFmpegPCMAudio", FakeSource)
    await soundboard.soundboard.callback(soundboard, it, choices[0].value)
    assert it.last == "🔊 Suono riprodotto"
    assert guild.voice_client.played[0].url.endswith(".wav") and "global" in guild.voice_client.played[0].url

    # lo toglie dalla dashboard: sparisce subito dall'autocomplete e il comando risponde "non trovato"
    async with dash.session.delete(f"{dash.base}/api/sounds/{data['sound']['id']}", headers=dash.headers()) as r:
        assert r.status == 200
    assert await soundboard.sound_autocomplete(it, "go") == []
    again = FakeInteraction(guild, channel)
    await soundboard.soundboard.callback(soundboard, again, choices[0].value)
    assert again.last == "❌ Suono non trovato."


async def test_voices_and_models_managed_in_the_dashboard_are_what_the_commands_offer(bot, dash):
    await storage.sync_guilds(bot.db, [(7, "Casa", None, 3), (8, "Ufficio", None, 2)])
    status, voice = await dash.upload("/api/voices", wav_bytes(2), "m.wav", name="Mario", guild="7")
    assert status == 201
    status, model = await dash.upload("/api/rvc", zip_bytes({"m.pth": b"p" * 100}), "m.zip", name="Voce Uno", guild_ids="8")
    assert status == 201

    guild7, guild8 = FakeGuild(7), FakeGuild(8)
    speakers = bot.get_cog("Create_Speaker")
    assert [c.name for c in await speakers.autocomplete_speakers(FakeInteraction(guild7), "")] == ["Mario"]
    assert await speakers.autocomplete_speakers(FakeInteraction(guild8), "") == []

    cover = bot.get_cog("AICover")
    assert await cover.model_autocomplete(FakeInteraction(guild7), "") == []          # limitato al server 8
    assert [c.name for c in await cover.model_autocomplete(FakeInteraction(guild8), "")] == ["Voce Uno"]

    async with dash.session.patch(f"{dash.base}/api/rvc/{model['model']['id']}", json={"guild_ids": []}, headers=dash.headers()) as r:
        assert r.status == 200
    assert [c.name for c in await cover.model_autocomplete(FakeInteraction(guild7), "")] == ["Voce Uno"]


async def test_the_bot_side_changes_appear_in_the_dashboard_and_the_audit_log(bot, dash):
    """Una voce registrata con /new-speaker (cog) è subito visibile e gestibile dalla dashboard."""
    speakers = bot.get_cog("Create_Speaker")
    folder = storage.voices_dir(7)
    folder.mkdir(parents=True)
    (folder / "alice_1.wav").write_bytes(wav_bytes(4))
    await speakers.save_speaker(7, "alice", "alice_1.wav", 4.0)

    async with dash.session.get(f"{dash.base}/api/voices?guild=7") as r:
        voices = (await r.json())["voices"]
    assert [(v["name"], v["duration"]) for v in voices] == [("alice", 4.0)]
    async with dash.session.get(f"{dash.base}/api/audit") as r:
        entries = (await r.json())["entries"]
    assert ("bot", "voice.add") in [(e["actor"], e["action"]) for e in entries]
