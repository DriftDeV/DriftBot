"""
Test del cog ACE-Step contro un finto server HTTP che segue il contratto documentato di
ACE-Step 1.5 (busta {data, code, error, timestamp, extra}; /release_task, /query_result, /v1/audio).
Nessuna GPU né modello: si verifica il client, non la qualità della musica.
"""

import asyncio
import json
from types import SimpleNamespace

import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from discord.ext import commands

from cogs import ace_step_cog as ace
from cogs.ace_step_cog import AceStepConfig, AceStepMusic
from fakes import FakeGuild, FakeInteraction, make_channel

AUDIO = b"ID3" + b"\x01" * 2000


def envelope(data, code=200, error=None):
    return web.json_response({"data": data, "code": code, "error": error, "timestamp": 1, "extra": None})


class FakeAceStep:
    """Server ACE-Step finto. Le proprietà pubbliche regolano il comportamento."""

    def __init__(self):
        self.api_key = ""              # se valorizzata, richiede Authorization: Bearer
        self.running_polls = 0         # quante volte /query_result risponde "in corso" prima del successo
        self.final_status = 1          # stato finale del task: 1 ok, 2 fallito
        self.item_failed = False       # task ok ma brano interno fallito
        self.never_finish = False
        self.gate = None               # asyncio.Event: finché non è impostato il task resta in corso
        self.forget_tasks = False
        self.release_http = 200
        self.release_code = 200
        self.bad_json = False
        self.file_ref = "/v1/audio?path=%2Ftmp%2Fapi_audio%2Fabc.mp3"
        self.audio = AUDIO
        self.chunked = False
        self.queue_position = 1
        self.submitted = []
        self.polls = 0
        self.downloads = 0
        self.headers_seen = []

    def app(self):
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_post("/release_task", self.release_task)
        app.router.add_post("/query_result", self.query_result)
        app.router.add_get("/v1/audio", self.get_audio)
        return app

    def _auth_ok(self, request):
        self.headers_seen.append(dict(request.headers))
        return not self.api_key or request.headers.get("Authorization") == f"Bearer {self.api_key}"

    async def health(self, request):
        return envelope({"status": "ok"})

    async def release_task(self, request):
        if not self._auth_ok(request):
            return web.json_response({"detail": "Unauthorized"}, status=401)
        if self.release_http != 200:
            return web.json_response({"detail": "x"}, status=self.release_http)
        if self.bad_json:
            return web.Response(text="<html>non json</html>", content_type="text/html")
        body = await request.json()
        self.submitted.append(body)
        if self.release_code != 200:
            return envelope(None, code=self.release_code, error="Qualcosa è andato storto /home/segreto")
        return envelope({"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "queued",
                         "queue_position": self.queue_position})

    async def query_result(self, request):
        if not self._auth_ok(request):
            return web.json_response({"detail": "Unauthorized"}, status=401)
        body = await request.json()
        task_id = body["task_id_list"][0]
        self.polls += 1
        if self.forget_tasks:
            return envelope([])
        waiting = self.never_finish or (self.gate is not None and not self.gate.is_set()) \
            or self.polls <= self.running_polls
        if waiting:
            return envelope([{"task_id": task_id, "status": 0, "result": "[]"}])
        if self.final_status == 2:
            return envelope([{"task_id": task_id, "status": 2, "result": "[]"}])
        inner = {"file": self.file_ref, "status": 2 if self.item_failed else 1,
                 "metas": {"bpm": 120, "duration": 30, "keyscale": "C major"}, "seed_value": "1"}
        return envelope([{"task_id": task_id, "status": 1, "result": json.dumps([inner])}])

    async def get_audio(self, request):
        self.downloads += 1
        if self.chunked:
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(self.audio)
            await response.write_eof()
            return response
        return web.Response(body=self.audio, content_type="audio/mpeg")


@pytest.fixture
async def srv():
    fake = FakeAceStep()
    server = TestServer(fake.app())
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    yield fake
    await server.close()


def make_cog(srv, **overrides):
    config = AceStepConfig(base_url=srv.url, poll_interval=0.01, timeout=5, max_seconds=180, **overrides)
    return AceStepMusic(SimpleNamespace(), config)


@pytest.fixture
async def env(srv):
    cog = make_cog(srv)
    guild = FakeGuild(7)
    guild.filesize_limit = 10 * 1024 * 1024
    channel = make_channel(guild)
    yield SimpleNamespace(cog=cog, srv=srv, guild=guild, channel=channel)
    await cog.cog_unload()


async def run(env, prompt="lofi hip hop, piano", durata=30, testo=None, user_id=42):
    it = FakeInteraction(env.guild, env.channel, user_id=user_id)
    await env.cog.ace_step.callback(env.cog, it, prompt, durata, testo)
    return it


def final(it):
    """Ultima modifica del messaggio di risposta."""
    return it.edits[-1]


# ------------------------------------------------------------------ percorso felice

async def test_generates_and_delivers_the_track(env):
    env.srv.running_polls = 2
    it = await run(env)

    result = final(it)
    assert result["embed"].title == "🎵 Musica generata"
    fields = {f.name: f.value for f in result["embed"].fields}
    assert fields["Prompt"] == "lofi hip hop, piano"
    assert "30s" in fields["Dettagli"] and "strumentale" in fields["Dettagli"]
    assert "120 BPM" in fields["Dettagli"] and "C major" in fields["Dettagli"]
    attachment = result["attachments"][0]
    assert attachment.fp.read() == AUDIO and attachment.filename == "ace-step-lofi-hip-hop-piano.mp3"
    assert result["allowed_mentions"].everyone is False

    # prima del risultato ha avvisato l'utente che stava componendo
    assert any("componendo" in (e.get("content") or "") for e in it.edits[:-1])
    assert it._done and env.cog._active_users == set()


async def test_request_body_follows_the_documented_contract(env):
    await run(env, prompt="  synthwave  ", durata=45)
    body = env.srv.submitted[0]
    assert body == {"prompt": "synthwave", "lyrics": "[Instrumental]", "audio_duration": 45,
                    "batch_size": 1, "audio_format": "mp3", "use_random_seed": True,
                    "task_type": "text2music"}


async def test_lyrics_are_passed_through(env):
    it = await run(env, testo="  [verse]\nciao mondo  ")
    assert env.srv.submitted[0]["lyrics"] == "[verse]\nciao mondo"
    assert "con testo" in {f.name: f.value for f in final(it)["embed"].fields}["Dettagli"]


async def test_duration_is_clamped_to_the_configured_maximum(env):
    env.cog.config.max_seconds = 60
    await run(env, durata=500)
    assert env.srv.submitted[0]["audio_duration"] == 60


async def test_queue_position_is_shown(env):
    env.srv.queue_position = 3
    it = await run(env)
    assert any("posizione 3" in (e.get("content") or "") for e in it.edits)


async def test_absolute_link_on_same_server_is_accepted(env):
    env.srv.file_ref = f"{env.srv.url}/v1/audio?path=%2Ftmp%2Fx.mp3"
    it = await run(env)
    assert final(it)["attachments"][0].fp.read() == AUDIO


# ------------------------------------------------------------------------ errori

async def message(it):
    return final(it)["content"]


async def test_server_unreachable_gives_a_clear_message(srv):
    cog = AceStepMusic(SimpleNamespace(), AceStepConfig(base_url="http://127.0.0.1:1", poll_interval=0.01))
    guild = FakeGuild(7)
    guild.filesize_limit = 10_000_000
    it = FakeInteraction(guild, make_channel(guild))
    await cog.ace_step.callback(cog, it, "jazz", 30, None)
    assert "non è raggiungibile" in final(it)["content"]
    assert cog._active_users == set()          # l'utente può riprovare
    await cog.cog_unload()


async def test_api_key_is_sent_and_wrong_key_is_reported(srv):
    srv.api_key = "segreta"
    guild = FakeGuild(7)
    guild.filesize_limit = 10_000_000
    channel = make_channel(guild)

    good = make_cog(srv, api_key="segreta")
    it = FakeInteraction(guild, channel)
    await good.ace_step.callback(good, it, "jazz", 30, None)
    assert final(it)["embed"].title == "🎵 Musica generata"
    assert all(h.get("Authorization") == "Bearer segreta" for h in srv.headers_seen)
    await good.cog_unload()

    bad = make_cog(srv, api_key="sbagliata")
    it = FakeInteraction(guild, channel)
    await bad.ace_step.callback(bad, it, "jazz", 30, None)
    assert "API key" in final(it)["content"]
    await bad.cog_unload()


@pytest.mark.parametrize("http_status, expected", [(429, "coda del server"), (500, "HTTP 500"), (403, "API key")])
async def test_http_errors_are_mapped(env, http_status, expected):
    env.srv.release_http = http_status
    it = await run(env)
    assert expected in await message(it)


async def test_generation_failures(env):
    env.srv.final_status = 2
    assert "fallita" in await message(await run(env))
    env.srv.final_status, env.srv.item_failed = 1, True
    assert "fallita" in await message(await run(env))


async def test_timeout_when_server_never_finishes(env):
    env.srv.never_finish = True
    env.cog.config.timeout = 0.2
    it = await run(env)
    assert "tempo massimo" in await message(it)
    assert env.cog._active_users == set()


async def test_server_forgot_the_task(env):
    env.srv.forget_tasks = True
    assert "non conosce più" in await message(await run(env))


async def test_garbage_responses_and_error_envelopes_hide_details(env):
    env.srv.bad_json = True
    assert "non valida" in await message(await run(env))

    env.srv.bad_json, env.srv.release_code = False, 500
    text = await message(await run(env))
    assert "segnalato un errore" in text and "segreto" not in text   # niente dettagli interni all'utente


async def test_unexpected_exception_is_contained(env, monkeypatch):
    async def boom(*args, **kwargs):
        raise ValueError("dettagli interni")

    monkeypatch.setattr(ace.AceStepClient, "submit", boom)
    it = await run(env)
    assert "Errore imprevisto" in await message(it) and "dettagli" not in await message(it)
    assert env.cog._active_users == set()


# ---------------------------------------------------------------- limiti del file

async def test_file_too_big_for_the_server_is_refused(env):
    env.guild.filesize_limit = 500          # il brano pesa ~2000 byte
    assert "Discord accetta al massimo" in await message(await run(env))


async def test_size_limit_also_enforced_when_server_does_not_declare_length(env):
    env.srv.chunked = True                  # niente Content-Length
    env.guild.filesize_limit = 500
    assert "Discord accetta al massimo" in await message(await run(env))


async def test_link_to_another_host_is_never_followed(env):
    env.srv.file_ref = "http://evil.example/steal.mp3"
    assert "link audio non valido" in await message(await run(env))
    assert env.srv.downloads == 0


# ------------------------------------------------------------------ concorrenza

async def test_one_generation_per_user_and_global_limit(env):
    env.srv.gate = asyncio.Event()
    env.cog.config.max_pending = 2

    first = asyncio.create_task(run(env, user_id=1))
    second = asyncio.create_task(run(env, user_id=2))
    while len(env.cog._active_users) < 2:
        await asyncio.sleep(0.01)

    same_user = await run(env, user_id=1)
    assert "già una generazione" in same_user.last and same_user.sent[-1][1]["ephemeral"]
    third = await run(env, user_id=3)
    assert "Troppe richieste" in third.last and len(env.srv.submitted) == 2

    env.srv.gate.set()
    for task in (first, second):
        assert final(await task)["embed"].title == "🎵 Musica generata"
    assert env.cog._active_users == set()


async def test_expired_interaction_falls_back_to_the_channel(env):
    it = FakeInteraction(env.guild, env.channel)
    it.edit_error = discord.NotFound(SimpleNamespace(status=404, reason="x"), "Unknown Webhook")
    await env.cog.ace_step.callback(env.cog, it, "jazz", 30, None)
    content, kwargs = it.channel.sent[-1]
    assert kwargs["file"].fp.read() == AUDIO and kwargs["embed"].title == "🎵 Musica generata"


# ------------------------------------------------------------ configurazione e registrazione

async def test_health_check(srv):
    cog = make_cog(srv)
    assert await cog._client().health() is True
    await cog.cog_unload()
    down = AceStepMusic(SimpleNamespace(), AceStepConfig(base_url="http://127.0.0.1:1"))
    assert await down._client().health() is False
    await down.cog_unload()


def test_config_from_env(monkeypatch):
    for var in ("ACESTEP_API_URL", "ACESTEP_API_KEY", "ACESTEP_MAX_SECONDS", "ACESTEP_TIMEOUT",
                "ACESTEP_MAX_PENDING", "ACESTEP_AUDIO_FORMAT"):
        monkeypatch.delenv(var, raising=False)
    default = AceStepConfig.from_env()
    assert (default.base_url, default.max_seconds, default.audio_format) == ("http://127.0.0.1:8001", 180, "mp3")

    monkeypatch.setenv("ACESTEP_API_URL", " http://gpu-box:9000/ ")
    monkeypatch.setenv("ACESTEP_MAX_SECONDS", "99999")        # oltre il massimo del server: limitato a 600
    monkeypatch.setenv("ACESTEP_TIMEOUT", "non-un-numero")    # valore non valido: default
    monkeypatch.setenv("ACESTEP_AUDIO_FORMAT", "exe")         # formato non ammesso: mp3
    config = AceStepConfig.from_env()
    assert config.base_url == "http://gpu-box:9000"
    assert config.max_seconds == 600 and config.timeout == 600 and config.audio_format == "mp3"


def test_filename_is_safe():
    make = AceStepMusic._filename
    assert make("Lo-Fi Hip Hop!!", "mp3") == "ace-step-lo-fi-hip-hop.mp3"
    for evil in ("../../etc/passwd; rm -rf /", "🎵🎵🎵", "a" * 500):
        name = make(evil, "flac")
        assert "/" not in name and ".." not in name and len(name) <= 60 and name.endswith(".flac")


async def test_command_is_registered_with_the_right_options():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    await bot.load_extension("cogs.ace_step_cog")
    command = bot.tree.get_command("ace-step")
    params = {p.name: p for p in command.parameters}
    assert params["prompt"].required and (params["prompt"].min_value, params["prompt"].max_value) == (3, 500)
    assert (params["durata"].min_value, params["durata"].max_value) == (10, ace.MAX_SECONDS)
    assert params["durata"].default == 30 and not params["durata"].required
    assert not params["testo"].required and params["testo"].max_value == 2000
    await bot.close()
