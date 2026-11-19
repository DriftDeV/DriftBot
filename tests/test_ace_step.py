"""
Test del cog ACE-Step contro un finto server HTTP che segue il contratto documentato di
ACE-Step 1.5 (busta {data, code, error, timestamp, extra}; /release_task, /query_result, /v1/audio).
Nessuna GPU né modello: si verifica il client, non la qualità della musica.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from aiohttp.test_utils import TestServer
from discord.ext import commands

from cogs import ace_step_cog as ace
from cogs.ace_step_cog import AceStepConfig, AceStepMusic
from text_llm import LLMConfig
from fake_servers import AUDIO, FakeAceStep
from fakes import FakeGuild, FakeInteraction, FakeVC, make_channel

NO_LLM = LLMConfig(enabled=False)

pytestmark = pytest.mark.usefixtures("instant_playback")


@pytest.fixture
async def srv():
    fake = FakeAceStep()
    server = TestServer(fake.app())
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    yield fake
    await server.close()


def make_cog(srv, **overrides):
    overrides.setdefault("llm", NO_LLM)     # questi test riguardano solo ACE-Step: l'LLM è provato altrove
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


async def run(env, prompt="lofi hip hop, piano", durata=30, testo=None, user_id=42,
              modello="ace", livello="veloce", lingua=None, strumentale=False):
    it = FakeInteraction(env.guild, env.channel, user_id=user_id)
    await env.cog.ai_music.callback(env.cog, it, prompt, modello, durata, testo, lingua, strumentale, livello)
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
    assert "attachments" not in result and "Riproduco in" in result["content"]   # niente file: lo suona il bot
    assert env.guild.voice_client.played[0].original.url.getvalue() == AUDIO
    assert result["allowed_mentions"].everyone is False

    # prima del risultato ha avvisato l'utente che stava componendo
    assert any("componendo" in (e.get("content") or "") for e in it.edits[:-1])
    assert it._done and env.cog._active_users == set()


async def test_request_body_follows_the_documented_contract(env):
    await run(env, prompt="  synthwave  ", durata=45)
    body = env.srv.submitted[0]
    assert body == {"prompt": "synthwave", "lyrics": "[Instrumental]", "vocal_language": "it",
                    "audio_duration": 45,
                    "batch_size": 1, "audio_format": "mp3", "use_random_seed": True,
                    "task_type": "text2music",
                    "thinking": True, "lm_temperature": 0.7, "inference_steps": 8,
                    "use_cot_caption": False, "use_cot_language": False}


async def test_thinking_is_off_without_a_lm_model(srv):
    cog = make_cog(srv, lm_model="")
    guild = FakeGuild(7)
    it = FakeInteraction(guild, make_channel(guild))
    await cog.ai_music.callback(cog, it, "jazz", "ace", 30, None)
    assert srv.submitted[0]["thinking"] is False
    await cog.cog_unload()


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
    await run(env)
    assert env.guild.voice_client.played[0].original.url.getvalue() == AUDIO


# ------------------------------------------------------------------- riproduzione in vocale

async def test_bot_joins_the_voice_channel_plays_and_leaves(env):
    await run(env)
    vc = env.guild.voice_client
    assert vc.channel is env.channel and len(vc.played) == 1
    assert vc.connected is False                    # era entrato apposta: a brano finito esce


async def test_bot_stays_if_it_was_already_in_the_channel(env):
    env.guild.voice_client = FakeVC(env.channel)
    await run(env)
    assert env.guild.voice_client.connected is True


async def test_user_must_be_in_a_voice_channel(env):
    it = FakeInteraction(env.guild, None)
    await env.cog.ai_music.callback(env.cog, it, "jazz", "ace", 30, None)
    assert "canale vocale" in it.last and it.sent[-1][1]["ephemeral"]
    assert env.srv.submitted == []                  # niente generazione a vuoto


async def test_file_is_attached_when_the_bot_is_busy_with_other_audio(env):
    busy = FakeVC(env.channel)
    busy.playing = True
    env.guild.voice_client = busy
    result = final(await run(env))
    assert "in vocale" in result["content"] and result["attachments"][0].fp.read() == AUDIO
    assert busy.played == []


async def test_big_file_is_not_attached_when_voice_fails(env):
    env.guild.filesize_limit = 500                  # il brano pesa ~2000 byte
    env.channel.connect = lambda cls=None: (_ for _ in ()).throw(RuntimeError("no"))
    result = final(await run(env))
    assert "troppo grande" in result["content"] and "attachments" not in result


# ------------------------------------------------------------------ avvio automatico

class FakeProc:
    """Popen finto: `ready` (se impostato) rende sano il finto server, come farebbe l'avvio vero."""
    def __init__(self, srv=None, exit_code=None):
        self.srv, self.exit_code, self.pid = srv, exit_code, 1234

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.exit_code = -15

    def wait(self, timeout=None):
        return self.exit_code


@pytest.fixture
def autostart(srv, tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(ace.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(ace.AceStepMusic, "_free_ram_gb", staticmethod(lambda: 64.0))

    def popen(cmd, **kwargs):
        launched.append((cmd, kwargs))
        srv.healthy = True                           # il server "parte" subito
        return FakeProc(srv)

    monkeypatch.setattr(ace.subprocess, "Popen", popen)
    srv.healthy = False
    return SimpleNamespace(launched=launched, dir=str(tmp_path))


async def test_server_is_started_when_down_and_generation_continues(env, autostart):
    env.cog.config.server_dir = autostart.dir
    it = await run(env)
    cmd, kwargs = autostart.launched[0]
    assert cmd[1:4] == ["run", "acestep-api", "--host"] and "--init-llm" in cmd
    assert cmd[cmd.index("--lm-model-path") + 1] == "acestep-5Hz-lm-0.6B"
    assert kwargs["cwd"] == autostart.dir and kwargs["start_new_session"] is True
    assert any("Avvio ACE-Step" in (e.get("content") or "") for e in it.edits)
    assert final(it)["embed"].title == "🎵 Musica generata"


async def test_rocm_venv_is_preferred_over_uv_run(env, autostart):
    python = Path(autostart.dir) / "venv_rocm" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    env.cog.config.server_dir = autostart.dir
    await run(env)
    cmd, kwargs = autostart.launched[0]
    assert cmd[0] == str(python) and "uv" not in cmd[0] and "--init-llm" in cmd
    assert kwargs["env"]["ACESTEP_LM_BACKEND"] == "pt" and kwargs["env"]["MIOPEN_FIND_MODE"] == "FAST" \
        and kwargs["env"]["ACESTEP_ROCM_DTYPE"] == "bfloat16"


async def test_tts_model_is_released_before_acestep_uses_the_gpu(env):
    order = []

    class FakeTTS:
        async def release_gpu(self):
            order.append("tts_released")

    env.cog.bot = SimpleNamespace(get_cog=lambda name: FakeTTS() if name == "TTSCog" else None)
    await run(env)
    assert order == ["tts_released"] and env.srv.submitted      # prima il TTS libera la VRAM, poi si genera


async def test_release_gpu_stops_only_a_server_started_by_the_bot(env, autostart):
    env.cog.config.server_dir = autostart.dir
    await env.cog.release_gpu()                      # niente avviato da noi: non fa nulla
    await run(env)
    proc = env.cog._servers["ace-veloce"]
    assert proc.poll() is None
    await env.cog.release_gpu()
    assert proc.poll() == -15 and env.cog._servers == {}


async def test_unloading_the_cog_stops_the_server_it_started(env, autostart):
    env.cog.config.server_dir = autostart.dir
    await run(env)
    proc = env.cog._servers["ace-veloce"]
    await env.cog.cog_unload()
    assert proc.poll() == -15


# ------------------------------------------------------------ modelli e livelli (/ai-music)

def port_of(srv) -> int:
    return int(srv.url.rsplit(":", 1)[1])


@pytest.fixture
def xl(env, autostart):
    """ACE-Step con il checkpoint XL presente e la porta "accurata" puntata al finto server."""
    (Path(autostart.dir) / "checkpoints" / "acestep-v15-xl-turbo").mkdir(parents=True)
    env.cog.config.server_dir, env.cog.config.accurate_port = autostart.dir, port_of(env.srv)
    return autostart


@pytest.fixture
def heart(env, autostart):
    """HeartMuLa "installato" (venv + ckpt) con la porta del wrapper puntata al finto server."""
    python = Path(autostart.dir) / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    (Path(autostart.dir) / "ckpt").mkdir()
    env.cog.config.heartmula_dir, env.cog.config.heartmula_port = autostart.dir, port_of(env.srv)
    return autostart


async def test_unsupported_combinations_and_missing_installs_are_refused_privately(env):
    for kwargs, expected in [
        (dict(modello="heartmula", livello="accurata"), "un solo livello"),
        (dict(modello="heartmula", strumentale=True), "canta sempre"),
        (dict(modello="heartmula"), "non è installato"),
        (dict(modello="ace", livello="accurata"), "richiede ACE-Step installato"),
    ]:
        it = await run(env, **kwargs)
        assert expected in it.last and it.sent[-1][1]["ephemeral"] is True, kwargs
    env.cog.config.server_dir = "/tmp/acestep-che-non-esiste-davvero"
    assert "~19 GB" in (await run(env, livello="accurata")).last           # checkpoint XL da scaricare
    assert env.srv.submitted == [] and env.cog._active_users == set()


async def test_accurate_level_starts_the_xl_backend_on_cpu_with_its_own_port_and_timeout(env, xl):
    env.srv.running_polls = 1                                   # il primo controllo dice "in corso": parte l'annuncio
    it = await run(env, livello="accurata")
    cmd, kwargs = xl.launched[0]
    assert kwargs["env"]["ACESTEP_CONFIG_PATH"] == "acestep-v15-xl-turbo" and kwargs["env"]["ACESTEP_DEVICE"] == "cpu"
    assert cmd[cmd.index("--port") + 1] == str(port_of(env.srv))
    assert env.cog._launch_spec(ace.BACKENDS[("ace", "accurata")], 1)[3].name == "acestep-api-xl.log"   # log a parte
    assert env.cog._launch_spec(ace.BACKENDS[("ace", "veloce")], 1)[3].name == "acestep-api.log"
    assert "ace-accurata" in env.cog._servers
    assert env.cog._client(ace.BACKENDS[("ace", "accurata")]).config.timeout == 3600
    assert env.cog._client().config.timeout == env.cog.config.timeout          # il livello veloce non cambia
    assert final(it)["embed"].footer.text.startswith("ACE-Step 1.5 XL (CPU)")
    assert any("su CPU" in (e.get("content") or "") for e in it.edits)


async def test_switching_backend_stops_the_previous_one_to_free_vram_and_ram(env, xl):
    xl.launched.clear()
    env.srv.healthy = False
    await run(env)                                              # ace veloce: il bot lo avvia
    fast = env.cog._servers["ace-veloce"]
    assert fast.poll() is None and len(xl.launched) == 1
    env.srv.healthy = False                                     # (il finto server risponde sempre alla stessa porta)
    await run(env, livello="accurata")
    assert set(env.cog._servers) == {"ace-accurata"}
    assert fast.poll() == -15                                   # il turbo è stato spento prima di partire l'XL


async def test_heartmula_is_slow_so_it_gets_shorter_durations_a_longer_timeout_and_an_estimate(env, heart):
    env.srv.running_polls = 1
    it = await run(env, modello="heartmula", testo="[Verse]\nuno due tre\nquattro cinque", durata=None)
    assert env.srv.submitted[0]["audio_duration"] == 60                     # default più basso di quello di ACE-Step (100)
    assert any("circa 6 minuti" in (e.get("content") or "") for e in it.edits)   # 60 s x 5 + 30 s fissi = 330 s = 6 minuti
    await run(env, modello="heartmula", testo="[Verse]\nuno due tre\nquattro cinque", durata=250)
    assert env.srv.submitted[1]["audio_duration"] == 120                    # tetto di HeartMuLa
    backend = ace.BACKENDS[("heartmula", "veloce")]
    assert env.cog._client(backend, 120).config.timeout == int(120 * 5 * 1.5) + 600
    assert env.cog._client(backend).config.timeout == env.cog.config.timeout   # senza durata: invariato


async def test_heartmula_gets_caption_lyrics_and_duration_only_and_warns_about_italian(env, heart):
    env.cog.config.llm = LLMConfig(enabled=False)
    it = await run(env, modello="heartmula", testo="[Verse]\nuno due tre\nquattro cinque", durata=45)
    body = env.srv.submitted[0]
    assert body == {"prompt": "lofi hip hop, piano", "lyrics": "[Verse]\nuno due tre\nquattro cinque", "audio_duration": 45}
    cmd, kwargs = heart.launched[0]
    assert cmd[1].endswith("heartmula_server.py") and kwargs["env"]["HEARTMULA_CKPT"] == str(Path(heart.dir) / "ckpt")
    embed = final(it)["embed"]
    assert embed.footer.text.startswith("HeartMuLa 3B")
    assert "pronuncia può essere imprecisa" in {f.name: f.value for f in embed.fields}["⚠️ Nota"]

    it = await run(env, modello="heartmula", testo="[Verse]\none two three\nfour five six", lingua="en")
    assert "⚠️ Nota" not in {f.name for f in final(it)["embed"].fields}      # l'inglese è tra le lingue dichiarate


async def test_not_enough_free_ram_is_reported_before_starting_a_heavy_backend(env, xl, monkeypatch):
    monkeypatch.setattr(ace.AceStepMusic, "_free_ram_gb", staticmethod(lambda: 9.0))
    text = await message(await run(env, livello="accurata"))
    assert "21 GB di RAM libera" in text and "ora ce ne sono 9" in text
    assert xl.launched == [] and env.cog._active_users == set()


async def test_server_already_running_is_not_started_again(env, autostart):
    env.srv.healthy = True
    env.cog.config.server_dir = autostart.dir
    await run(env)
    assert autostart.launched == []


async def test_no_autostart_without_server_dir(env, autostart):
    env.cog.config.server_dir = ""
    await run(env)
    assert autostart.launched == []                 # nessuna cartella ACE-Step: non si avvia nulla


async def test_remote_server_is_never_started(autostart):
    cog = AceStepMusic(SimpleNamespace(), AceStepConfig(
        base_url="http://gpu-box:1", server_dir=autostart.dir, llm=NO_LLM, poll_interval=0.01))
    guild = FakeGuild(7)
    it = FakeInteraction(guild, make_channel(guild))
    await cog.ai_music.callback(cog, it, "jazz", "ace", 30, None)
    assert autostart.launched == [] and "non è raggiungibile" in final(it)["content"]
    await cog.cog_unload()


async def test_server_that_dies_at_startup_is_reported(env, autostart, monkeypatch):
    env.cog.config.server_dir = autostart.dir
    monkeypatch.setattr(ace.subprocess, "Popen", lambda cmd, **kw: FakeProc(exit_code=1))
    assert "si è chiuso all'avvio" in await message(await run(env))


async def test_startup_timeout_is_reported_and_the_process_is_reused(env, autostart, monkeypatch):
    env.cog.config.server_dir, env.cog.config.startup_timeout = autostart.dir, 0.05
    monkeypatch.setattr(ace.subprocess, "Popen", lambda cmd, **kw: autostart.launched.append(cmd) or FakeProc())
    assert "non è pronto" in await message(await run(env))
    assert "non è pronto" in await message(await run(env))
    assert len(autostart.launched) == 1             # il secondo tentativo aspetta lo stesso processo


def test_server_dir_from_env_or_sibling(monkeypatch, tmp_path):
    monkeypatch.setenv("ACESTEP_DIR", str(tmp_path))
    assert ace.find_server_dir() == str(tmp_path)
    monkeypatch.delenv("ACESTEP_DIR")
    assert ace.find_server_dir() in ("", str(Path(ace.__file__).resolve().parents[3] / "ACE-Step-1.5"))


# ------------------------------------------------------------------------ errori

async def message(it):
    return final(it)["content"]


async def test_server_unreachable_gives_a_clear_message(srv):
    cog = AceStepMusic(SimpleNamespace(), AceStepConfig(base_url="http://127.0.0.1:1", poll_interval=0.01, llm=NO_LLM))
    guild = FakeGuild(7)
    guild.filesize_limit = 10_000_000
    it = FakeInteraction(guild, make_channel(guild))
    await cog.ai_music.callback(cog, it, "jazz", "ace", 30, None)
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
    await good.ai_music.callback(good, it, "jazz", "ace", 30, None)
    assert final(it)["embed"].title == "🎵 Musica generata"
    assert all(h.get("Authorization") == "Bearer segreta" for h in srv.headers_seen)
    await good.cog_unload()

    bad = make_cog(srv, api_key="sbagliata")
    it = FakeInteraction(guild, channel)
    await bad.ai_music.callback(bad, it, "jazz", "ace", 30, None)
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

async def test_file_over_the_memory_cap_is_refused(env, monkeypatch):
    monkeypatch.setattr(ace, "MAX_AUDIO_BYTES", 500)    # il brano pesa ~2000 byte
    assert "oltre il limite" in await message(await run(env))


async def test_size_limit_also_enforced_when_server_does_not_declare_length(env, monkeypatch):
    env.srv.chunked = True                  # niente Content-Length
    monkeypatch.setattr(ace, "MAX_AUDIO_BYTES", 500)
    assert "oltre il limite" in await message(await run(env))


async def test_link_to_another_host_is_never_followed(env):
    env.srv.file_ref = "http://evil.example/steal.mp3"
    assert "link audio non valido" in await message(await run(env))
    assert env.srv.downloads == 0


# ------------------------------------------------------------------ concorrenza

async def test_one_generation_per_user_global_limit_and_serialization(env):
    env.srv.gate = asyncio.Event()
    env.cog.config.max_pending = 2

    first = asyncio.create_task(run(env, user_id=1))
    second = asyncio.create_task(run(env, user_id=2))
    while len(env.cog._active_users) < 2:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)

    same_user = await run(env, user_id=1)
    assert "già una generazione" in same_user.last and same_user.sent[-1][1]["ephemeral"]
    third = await run(env, user_id=3)
    assert "Troppe richieste" in third.last
    # un solo lavoro GPU alla volta: il secondo utente aspetta, non parte in parallelo
    assert len(env.srv.submitted) == 1

    env.srv.gate.set()
    for task in (first, second):
        assert final(await task)["embed"].title == "🎵 Musica generata"
    assert len(env.srv.submitted) == 2 and env.cog._active_users == set()


async def test_expired_interaction_falls_back_to_the_channel(env):
    it = FakeInteraction(env.guild, env.channel)
    it.edit_error = discord.NotFound(SimpleNamespace(status=404, reason="x"), "Unknown Webhook")
    await env.cog.ai_music.callback(env.cog, it, "jazz", "ace", 30, None)
    content, kwargs = it.channel.sent[-1]
    assert kwargs["file"] is None and kwargs["embed"].title == "🎵 Musica generata"   # il brano è in vocale
    # un embed da solo non notifica nessuno: nel canale si cita chi aveva chiesto il brano (e solo lui)
    assert content.startswith(it.user.mention) and "Riproduco in" in content
    assert kwargs["allowed_mentions"].users == [it.user] and kwargs["allowed_mentions"].everyone is False


# ------------------------------------------------------------ configurazione e registrazione

async def test_health_check(srv):
    cog = make_cog(srv)
    assert await cog._client().health() is True
    await cog.cog_unload()
    down = AceStepMusic(SimpleNamespace(), AceStepConfig(base_url="http://127.0.0.1:1", llm=NO_LLM))
    assert await down._client().health() is False
    await down.cog_unload()


def test_config_from_env(monkeypatch):
    for var in ("ACESTEP_API_URL", "ACESTEP_API_KEY", "ACESTEP_MAX_SECONDS", "ACESTEP_TIMEOUT",
                "ACESTEP_MAX_PENDING", "ACESTEP_AUDIO_FORMAT"):
        monkeypatch.delenv(var, raising=False)
    default = AceStepConfig.from_env()
    assert (default.base_url, default.max_seconds, default.audio_format) == ("http://127.0.0.1:8001", 300, "mp3")
    assert default.default_seconds == 100 and default.lm_model == "acestep-5Hz-lm-0.6B"

    monkeypatch.setenv("ACESTEP_API_URL", " http://gpu-box:9000/ ")
    monkeypatch.setenv("ACESTEP_MAX_SECONDS", "99999")        # oltre il massimo del server: limitato a 600
    monkeypatch.setenv("ACESTEP_TIMEOUT", "non-un-numero")    # valore non valido: default
    monkeypatch.setenv("ACESTEP_AUDIO_FORMAT", "exe")         # formato non ammesso: mp3
    config = AceStepConfig.from_env()
    assert config.base_url == "http://gpu-box:9000"
    assert config.max_seconds == 600 and config.timeout == 600 and config.audio_format == "mp3"


def test_filename_is_safe():   # il nome serve solo al file allegato di ripiego
    make = AceStepMusic._filename
    assert make("Lo-Fi Hip Hop!!", "mp3") == "ace-step-lo-fi-hip-hop.mp3"
    for evil in ("../../etc/passwd; rm -rf /", "🎵🎵🎵", "a" * 500):
        name = make(evil, "flac")
        assert "/" not in name and ".." not in name and len(name) <= 60 and name.endswith(".flac")


async def test_command_is_registered_with_the_right_options():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    await bot.load_extension("cogs.ace_step_cog")
    command = bot.tree.get_command("ai-music")
    params = {p.name: p for p in command.parameters}
    assert params["prompt"].required and (params["prompt"].min_value, params["prompt"].max_value) == (3, 500)
    assert (params["durata"].min_value, params["durata"].max_value) == (10, ace.MAX_SECONDS)
    assert not params["durata"].required and params["durata"].default is None   # None = durata di default
    assert not params["testo"].required and params["testo"].max_value == 2000
    assert [c.value for c in params["lingua"].choices] == ["it", "en", "es", "fr", "de", "pt"]
    assert not params["lingua"].required
    assert params["strumentale"].default is False
    assert params["modello"].required and [c.value for c in params["modello"].choices] == ["ace", "heartmula"]
    assert not params["livello"].required and params["livello"].default == "veloce"
    assert [c.value for c in params["livello"].choices] == ["veloce", "accurata"]
    assert bot.tree.get_command("ace-step") is None                              # il vecchio comando non esiste più
    await bot.close()
