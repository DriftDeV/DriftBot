"""Test dei cog: soundboard, creazione speaker, pipeline RVC, AI cover, TTS (senza GPU né rete)."""

import asyncio
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from discord.ext import voice_recv

import cogs
from cogs import Create_speaker as cs
from cogs import TTS_COG, ai_cover_cog, soundboards
from cogs.RVC import rvc
from fakes import FakeGuild, FakeInteraction, FakeSource, FakeVC, make_channel


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Cartella dati dei server isolata."""
    monkeypatch.setattr(cogs, "BASE_DATA_DIR", tmp_path / "data")
    return tmp_path / "data"


def http_error(status=401, text="Invalid Webhook Token"):
    return discord.HTTPException(SimpleNamespace(status=status, reason="x"), text)


# ============================================================= soundboard

@pytest.fixture
def sb(data_dir, monkeypatch):
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeSource)
    guild = FakeGuild(7)
    channel = make_channel(guild)
    sound_dir = data_dir / "7" / "soundboard"      # la cartella documentata nel README
    sound_dir.mkdir(parents=True)
    (sound_dir / "clap.wav").write_text("x")
    (sound_dir / "index.json").write_text(json.dumps({"Clap": "clap.wav"}))
    (data_dir / "secret.wav").write_text("x")
    return SimpleNamespace(cog=soundboards.Soundboards(SimpleNamespace()), guild=guild,
                           channel=channel, dir=sound_dir)


async def test_soundboard_plays_file_from_the_documented_folder(sb):
    it = FakeInteraction(sb.guild, sb.channel)
    await sb.cog.soundboard.callback(sb.cog, it, "clap.wav")
    assert it.last == "🔊 Suono riprodotto"
    assert sb.guild.voice_client.played[0].url.endswith("soundboard/clap.wav")


async def test_soundboard_always_answers_when_not_in_voice(sb):
    it = FakeInteraction(sb.guild, None)
    await sb.cog.soundboard.callback(sb.cog, it, "clap.wav")
    assert "canale vocale" in it.last and it.sent[-1][1].get("ephemeral")


async def test_soundboard_rejects_path_traversal(sb):
    for evil in ("../../secret.wav", "/etc/passwd", "..", "nope.wav"):
        it = FakeInteraction(sb.guild, sb.channel)
        await sb.cog.soundboard.callback(sb.cog, it, evil)
        assert it.last == "❌ Suono non trovato."
        # l'errore è privato: si risponde PRIMA del defer, perché dopo un defer pubblico Discord ignora `ephemeral`
        assert it.sent[-1][1].get("ephemeral") is True and not it.deferred
    assert sb.guild.voice_client is None       # non si è nemmeno connesso


async def test_soundboard_connection_and_ffmpeg_failures_are_reported(sb, monkeypatch):
    bad_channel = make_channel(sb.guild, fail_connect=True)
    it = FakeInteraction(sb.guild, bad_channel)
    await sb.cog.soundboard.callback(sb.cog, it, "clap.wav")
    assert "connettermi" in it.last

    def boom(path):
        raise RuntimeError("ffmpeg non trovato")

    monkeypatch.setattr(discord, "FFmpegPCMAudio", boom)
    it = FakeInteraction(sb.guild, sb.channel)
    await sb.cog.soundboard.callback(sb.cog, it, "clap.wav")
    assert "FFmpeg" in it.last


async def test_soundboard_autocomplete_survives_corrupt_index(sb):
    it = FakeInteraction(sb.guild, sb.channel)
    assert [c.name for c in await sb.cog.sound_autocomplete(it, "cl")] == ["Clap"]
    (sb.dir / "index.json").write_text("{rotto")
    assert await sb.cog.sound_autocomplete(it, "cl") == []


# ================================================================ speaker

class FakeRecv(voice_recv.VoiceRecvClient):
    def __init__(self, channel, listen_error=None):
        self.channel, self.listening, self.rec_sink = channel, False, None
        self.connected, self.playing, self.listen_error = True, False, listen_error

    def is_listening(self): return self.listening
    def is_playing(self): return self.playing
    def is_connected(self): return self.connected

    def listen(self, sink):
        if self.listen_error:
            raise self.listen_error
        self.listening, self.rec_sink = True, sink

    def stop_listening(self):
        self.listening = False
        self.rec_sink.cleanup()

    async def disconnect(self): self.connected = False
    async def move_to(self, channel): self.channel = channel


@pytest.fixture
def sp(data_dir):
    guild = FakeGuild(7)
    channel = make_channel(guild, "voce")
    return SimpleNamespace(cog=cs.Create_Speaker(SimpleNamespace()), guild=guild, channel=channel, dir=data_dir / "7" / "speakers")


def write_speakers(sp, speakers, aliases=None):
    sp.dir.mkdir(parents=True, exist_ok=True)
    (sp.dir / "index.json").write_text(json.dumps(speakers))
    (sp.dir / "alias.json").write_text(json.dumps(aliases or {}))


async def test_rename_speaker_works(sp):
    """Prima di questa correzione /rename-speaker andava sempre in NameError."""
    write_speakers(sp, {"bob": "bob_1.wav"})
    it = FakeInteraction(sp.guild, sp.channel)
    await sp.cog.rename_speaker.callback(sp.cog, it, "robert", "bob_1.wav")
    assert it.last == "✅ Speaker Rinominato!"
    assert json.loads((sp.dir / "index.json").read_text()) == {"robert": "bob_1.wav"}
    assert json.loads((sp.dir / "alias.json").read_text()) == {"bob": "robert"}


async def test_rename_speaker_errors(sp):
    write_speakers(sp, {"bob": "bob_1.wav", "eve": "eve_1.wav"})
    it = FakeInteraction(sp.guild, sp.channel)
    await sp.cog.rename_speaker.callback(sp.cog, it, "x", "inesistente.wav")
    assert "non trovato" in it.last
    await sp.cog.rename_speaker.callback(sp.cog, it, "eve", "bob_1.wav")   # nome già usato
    assert "Esiste già" in it.last
    await sp.cog.rename_speaker.callback(sp.cog, it, "   ", "bob_1.wav")
    assert "vuoto" in it.last
    assert json.loads((sp.dir / "index.json").read_text()) == {"bob": "bob_1.wav", "eve": "eve_1.wav"}


async def test_save_speaker_applies_alias_and_survives_corrupt_alias_file(sp):
    write_speakers(sp, {}, {"bob": "robert"})
    await sp.cog.save_speaker(7, "bob", "bob_2.wav")
    assert json.loads((sp.dir / "index.json").read_text()) == {"robert": "bob_2.wav"}
    (sp.dir / "alias.json").write_text("{rotto")
    await sp.cog.save_speaker(7, "eve", "eve_1.wav")
    assert json.loads((sp.dir / "index.json").read_text())["eve"] == "eve_1.wav"


async def test_recording_client_replaces_a_plain_voice_client(sp):
    plain = FakeVC(sp.channel)
    sp.guild.voice_client = plain
    created = {}

    async def connect(cls=None):
        created["cls"] = cls
        return "nuovo-client"

    sp.channel.connect = connect
    assert await sp.cog._get_recording_client(sp.channel, sp.guild) == "nuovo-client"
    assert created["cls"] is voice_recv.VoiceRecvClient and not plain.connected


async def test_recording_client_refuses_when_bot_is_busy_or_reuses_recv(sp):
    plain = FakeVC(sp.channel)
    plain.playing = True
    sp.guild.voice_client = plain
    with pytest.raises(RuntimeError, match="busy"):
        await sp.cog._get_recording_client(sp.channel, sp.guild)

    recv = FakeRecv(sp.channel)
    sp.guild.voice_client = recv
    assert await sp.cog._get_recording_client(sp.channel, sp.guild) is recv


async def start_recording(sp, monkeypatch, **recv_kwargs):
    recv = FakeRecv(sp.channel, **recv_kwargs)

    async def fake_client(channel, guild):
        return recv

    monkeypatch.setattr(sp.cog, "_get_recording_client", fake_client)
    it = FakeInteraction(sp.guild, sp.channel, name="alice")
    await sp.cog.create_speaker.callback(sp.cog, it, None)
    return it, recv


def panel(it):
    """Il pannello di registrazione: (embed, view) dell'ultima modifica del messaggio."""
    last = it.edits[-1]
    return last["embed"], last["view"]


async def click(view, user_id=42):
    """Simula il click sul pulsante «Interrompi» (passando prima dal controllo di chi preme)."""
    interaction = FakeInteraction(FakeGuild(7), None, user_id=user_id)
    if await view.interaction_check(interaction):
        await view.stop_button.callback(interaction)
    return interaction


async def test_recording_uses_a_single_private_message_without_server_paths(sp, monkeypatch):
    it, _ = await start_recording(sp, monkeypatch)
    # un solo messaggio ("Connessione...") che poi diventa il pannello: niente messaggio vecchio accanto
    assert len(it.sent) == 1 and "Connessione" in it.sent[0][0] and it.sent[0][1]["ephemeral"] is True
    embed, view = panel(it)
    assert it.edits[-1]["content"] is None and embed.title == "🎙️ Registrazione in corso"
    assert {f.name for f in embed.fields} == {"Inizio"}
    everything = " ".join([embed.title, embed.description or "", embed.footer.text or ""] + [f.value for f in embed.fields])
    assert str(sp.dir) not in everything and "/" not in everything.replace("<t:", "").replace(":R>", "")
    view.stop()


async def test_stop_button_turns_the_panel_into_the_saved_result(sp, monkeypatch):
    it, recv = await start_recording(sp, monkeypatch)
    _, view = panel(it)
    # a registrazione appena avviata lo speaker NON deve essere già in elenco
    assert not (sp.dir / "index.json").exists() or json.loads((sp.dir / "index.json").read_text()) == {}

    recv.rec_sink.write(it.user, SimpleNamespace(pcm=b"\0" * (cs.BYTES_PER_SECOND * 4)))
    pressed = await click(view)

    # risposta immediata (entro 3s): il pulsante sparisce subito e compare "Salvataggio in corso"
    assert pressed.message_edits[0]["view"] is None and "Salvataggio" in pressed.message_edits[0]["embed"].title
    # poi il pannello diventa il risultato: titolo, colore e testo finali, nessun pulsante, nessun "in corso" appeso
    final = pressed.edits[-1]
    assert final["view"] is None and final["embed"].title == "✅ Registrazione salvata"
    assert final["embed"].color == discord.Color.green() and "alice" in final["embed"].description
    assert "/tts-ai" in final["embed"].description and "in corso" not in final["embed"].title

    saved = json.loads((sp.dir / "index.json").read_text())
    assert list(saved) == ["alice"] and (sp.dir / saved["alice"]).exists()
    assert not recv.connected and not recv.listening


async def test_too_short_recording_is_discarded_and_reported_as_a_warning(sp, monkeypatch):
    it, recv = await start_recording(sp, monkeypatch)
    _, view = panel(it)
    recv.rec_sink.write(it.user, SimpleNamespace(pcm=b"\0" * 1000))
    pressed = await click(view)
    final = pressed.edits[-1]
    assert final["embed"].title == "⚠️ Registrazione non salvata" and "troppo breve" in final["embed"].description
    assert final["embed"].color == discord.Color.orange()
    assert list(sp.dir.glob("*.wav")) == []      # file eliminato
    assert not (sp.dir / "index.json").exists() or json.loads((sp.dir / "index.json").read_text()) == {}


async def test_a_second_click_does_nothing(sp, monkeypatch):
    it, recv = await start_recording(sp, monkeypatch)
    _, view = panel(it)
    recv.rec_sink.write(it.user, SimpleNamespace(pcm=b"\0" * (cs.BYTES_PER_SECOND * 4)))
    first = await click(view)
    second = await click(view)
    # il secondo click viene solo confermato: non rimette "Salvataggio in corso" sopra il risultato finale
    assert second.deferred and second.message_edits == [] and second.edits == []
    assert first.edits[-1]["embed"].title == "✅ Registrazione salvata"


async def test_only_the_user_who_started_the_recording_can_stop_it(sp, monkeypatch):
    it, recv = await start_recording(sp, monkeypatch)
    _, view = panel(it)
    intruder = await click(view, user_id=999)
    assert "Solo chi ha avviato" in intruder.last and intruder.sent[-1][1]["ephemeral"] is True
    assert recv.listening and not view._stopping          # la registrazione continua
    view.stop()


async def test_timeout_finishes_the_recording_and_updates_the_panel(sp, monkeypatch):
    it, recv = await start_recording(sp, monkeypatch)
    _, view = panel(it)
    recv.rec_sink.write(it.user, SimpleNamespace(pcm=b"\0" * (cs.BYTES_PER_SECOND * 4)))
    await view.on_timeout()
    final = it.edits[-1]
    assert final["view"] is None and final["embed"].title == "✅ Registrazione salvata"
    assert "Tempo massimo" in final["embed"].footer.text
    edits_before = len(it.edits)
    await view.on_timeout()                               # un secondo timeout non rifà nulla
    assert len(it.edits) == edits_before


async def test_timeout_after_the_button_was_pressed_is_a_noop(sp, monkeypatch):
    it, recv = await start_recording(sp, monkeypatch)
    _, view = panel(it)
    recv.rec_sink.write(it.user, SimpleNamespace(pcm=b"\0" * (cs.BYTES_PER_SECOND * 4)))
    await click(view)
    edits_before = len(it.edits)
    await view.on_timeout()
    assert len(it.edits) == edits_before


async def test_errors_replace_the_connecting_message_instead_of_adding_another(sp, monkeypatch):
    it, _ = await start_recording(sp, monkeypatch, listen_error=RuntimeError("già in ascolto"))
    assert "Impossibile avviare" in it.edits[-1]["content"] and len(it.sent) == 1
    assert list(sp.dir.glob("*.wav")) == []

    busy = FakeRecv(sp.channel)
    busy.listening = True
    async def busy_client(channel, guild):
        return busy
    monkeypatch.setattr(sp.cog, "_get_recording_client", busy_client)
    it = FakeInteraction(sp.guild, sp.channel)
    await sp.cog.create_speaker.callback(sp.cog, it, None)
    assert "già registrando" in it.edits[-1]["content"] and len(it.sent) == 1


async def test_speaker_command_requires_voice(sp):
    it = FakeInteraction(sp.guild, None)
    await sp.cog.create_speaker.callback(sp.cog, it, None)
    assert "canale vocale" in it.last


# ===================================================================== rvc

@pytest.fixture
def rv(tmp_path, monkeypatch):
    monkeypatch.setattr(rvc, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(rvc, "JOBS_DIR", tmp_path / "jobs")
    (tmp_path / "models" / "voce1").mkdir(parents=True)
    return tmp_path


def test_validate_url():
    assert rvc.validate_url("  https://youtu.be/abc  ") == "https://youtu.be/abc"
    for bad in ("file:///etc/passwd", "ytsearch:canzone", "javascript:alert(1)", "/home/u/x.wav", "", "https://"):
        with pytest.raises(rvc.CoverError):
            rvc.validate_url(bad)


def test_resolve_model_stays_inside_models_dir(rv):
    assert rvc.resolve_model("voce1") == (rv / "models" / "voce1").resolve()
    for bad in ("../../etc", "nope", "/etc/passwd", ""):
        with pytest.raises(rvc.CoverError):
            rvc.resolve_model(bad)


def test_rvc_device_works_for_cuda_and_rocm(monkeypatch):
    for reported, expected in (("cuda", "cuda:0"), ("cuda:1", "cuda:1"), ("cpu", "cpu"), ("mps", "mps")):
        monkeypatch.setattr(rvc.gpu_utils, "get_device", lambda r=reported: r)
        assert rvc.get_rvc_device() == expected


def test_job_dirs_are_isolated_and_cleanup_is_safe(rv):
    a, b = rvc.create_job_dir(1), rvc.create_job_dir(1)
    assert a != b and a.parent == rvc.JOBS_DIR
    (a / "out.wav").write_text("x")

    outside = rv / "important.txt"
    outside.write_text("x")
    rvc.cleanup_job(outside)                       # fuori da jobs/: mai toccato
    rvc.cleanup_job(None)
    assert outside.exists()

    rvc.cleanup_job(a / "out.wav")                 # accetta il file: elimina il job intero
    assert not a.exists() and b.exists()
    rvc.cleanup_job(b)
    assert not b.exists()


def test_stale_jobs_are_purged(rv):
    old, fresh = rvc.create_job_dir(1), rvc.create_job_dir(2)
    long_ago = time.time() - rvc.STALE_JOB_SECONDS - 60
    os.utime(old, (long_ago, long_ago))
    rvc.purge_stale_jobs()
    assert not old.exists() and fresh.exists()


def make_stems(job):
    stems = job / "separated" / "htdemucs" / "canzone_originale"
    stems.mkdir(parents=True)
    (stems / "vocals.wav").write_text("v")
    (stems / "no_vocals.wav").write_text("i")


@pytest.fixture
def job(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    wav = job_dir / "canzone_originale.wav"
    wav.write_text("x")
    return job_dir, wav


def test_demucs_falls_back_to_cpu_when_gpu_runs_out_of_memory(job, monkeypatch):
    """Vale per VRAM piena su NVIDIA ('CUDA out of memory') e su ROCm ('HIP out of memory')."""
    job_dir, wav = job
    monkeypatch.setattr(rvc.gpu_utils, "get_device", lambda: "cuda")
    calls = []

    def fake_run(cmd, **kwargs):
        device = cmd[cmd.index("-d") + 1]
        calls.append(device)
        if device != "cpu":
            return SimpleNamespace(returncode=1, stdout="", stderr="torch.OutOfMemoryError: HIP out of memory")
        make_stems(job_dir)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rvc.subprocess, "run", fake_run)
    vocals, instrumental = rvc._separate(job_dir, wav)
    assert calls == ["cuda", "cpu"]
    assert vocals.name == "vocals.wav" and instrumental.name == "no_vocals.wav"


def test_demucs_cpu_only_and_total_failure(job, monkeypatch):
    job_dir, wav = job
    monkeypatch.setattr(rvc.gpu_utils, "get_device", lambda: "cpu")
    calls = []

    def always_fail(cmd, **kwargs):
        calls.append(cmd[cmd.index("-d") + 1])
        return SimpleNamespace(returncode=1, stdout="", stderr="errore")

    monkeypatch.setattr(rvc.subprocess, "run", always_fail)
    with pytest.raises(rvc.CoverError):
        rvc._separate(job_dir, wav)
    assert calls == ["cpu"]

    def too_slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(rvc.subprocess, "run", too_slow)
    with pytest.raises(rvc.CoverError, match="troppo tempo"):
        rvc._separate(job_dir, wav)


def test_demucs_uses_absolute_paths_and_never_changes_cwd(job, monkeypatch):
    job_dir, wav = job
    monkeypatch.setattr(rvc.gpu_utils, "get_device", lambda: "cpu")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs=kwargs, cmd=cmd)
        make_stems(job_dir)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rvc.subprocess, "run", fake_run)
    before = os.getcwd()
    rvc._separate(job_dir, wav)
    assert os.getcwd() == before
    assert seen["kwargs"]["cwd"] == job_dir and seen["kwargs"]["timeout"] == rvc.DEMUCS_TIMEOUT
    assert str(job_dir / "separated") in seen["cmd"]


def test_download_errors_become_user_messages(job, monkeypatch):
    job_dir, _ = job
    opts_seen = {}

    class FakeYDL:
        mode = "error"

        def __init__(self, opts):
            opts_seen.update(opts)

        def __enter__(self): return self
        def __exit__(self, *a): return False

        def download(self, urls):
            if FakeYDL.mode == "error":
                raise rvc.yt_dlp.utils.DownloadError("HTTP 403 segreto")
            if FakeYDL.mode == "ok":
                (job_dir / "canzone_originale.wav").write_text("audio")

    monkeypatch.setattr(rvc.yt_dlp, "YoutubeDL", FakeYDL)
    (job_dir / "canzone_originale.wav").unlink()

    with pytest.raises(rvc.CoverError) as exc:
        rvc._download(job_dir, "https://x")
    assert "segreto" not in str(exc.value)

    FakeYDL.mode = "skipped"          # yt-dlp salta il video (troppo lungo) senza errore
    with pytest.raises(rvc.CoverError, match="più lungo"):
        rvc._download(job_dir, "https://x")

    FakeYDL.mode = "ok"
    assert rvc._download(job_dir, "https://x").name == "canzone_originale.wav"
    assert opts_seen["noplaylist"] is True and str(job_dir) in opts_seen["outtmpl"]
    assert callable(opts_seen["match_filter"])


def test_failed_pipeline_leaves_no_temp_files(rv, monkeypatch):
    def boom(job_dir, url):
        raise rvc.CoverError("download fallito")

    monkeypatch.setattr(rvc, "_download", boom)
    with pytest.raises(rvc.CoverError):
        rvc._pipeline(1, "voce1", "https://x", 0)
    assert list(rvc.JOBS_DIR.iterdir()) == []

    with pytest.raises(rvc.CoverError):            # input non valido: nemmeno crea il job
        rvc._pipeline(1, "voce1", "file:///etc/passwd", 0)
    with pytest.raises(rvc.CoverError):
        rvc._pipeline(1, "../../x", "https://x", 0)
    assert list(rvc.JOBS_DIR.iterdir()) == []


def test_rvc_version_detection(tmp_path, monkeypatch):
    (tmp_path / "vuota").mkdir()
    assert rvc.get_rvc_version(tmp_path / "vuota") == "v2"          # nessun .pth

    pth = tmp_path / "m.pth"
    pth.write_text("x")
    monkeypatch.setattr(rvc.torch, "load", lambda *a, **k: {"weight": {"dec.cond.weight": SimpleNamespace(shape=(256, 1))}})
    assert rvc.get_rvc_version(pth) == "v1"

    def broken(*a, **k):
        raise RuntimeError("checkpoint corrotto")

    monkeypatch.setattr(rvc.torch, "load", broken)
    assert rvc.get_rvc_version(pth) == "v2"                          # non solleva


# ============================================================= ai cover cog

@pytest.fixture
def ac(rv, monkeypatch):
    monkeypatch.setattr(ai_cover_cog, "IDLE_DISCONNECT", 0.01)
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeSource)
    guild = FakeGuild(7)
    channel = make_channel(guild)
    cog = ai_cover_cog.AICover(SimpleNamespace(get_cog=lambda name: None))
    yield SimpleNamespace(cog=cog, guild=guild, channel=channel, tmp=rv)
    for task in (cog.worker_task, cog._idle_task):
        if task:
            task.cancel()


def make_item(it, url="https://x", model="voce1"):
    return {"interaction": it, "url": url, "model": model, "Pitch": 0}


async def test_notify_falls_back_to_channel_when_token_expired(ac):
    it = FakeInteraction(ac.guild, ac.channel)
    it.followup_error = http_error()
    await ac.cog._notify(it, content="pronta")
    assert it.channel.sent == [("pronta", {})]

    async def broken_send(content=None, **kwargs):
        raise http_error(403, "Missing Permissions")

    it.channel.send = broken_send
    await ac.cog._notify(it, content="di nuovo")      # non solleva


async def test_ai_cover_command_validates_input(ac):
    callback = ac.cog.ai_cover.callback

    it = FakeInteraction(ac.guild, None)
    await callback(ac.cog, it, "https://x", "voce1", 0)
    assert "canale vocale" in it.last

    for url, model, expected in (("file:///etc/passwd", "voce1", "URL non valido"),
                                 ("https://x", "../../etc", "non trovato")):
        it = FakeInteraction(ac.guild, ac.channel)
        await callback(ac.cog, it, url, model, 0)
        assert expected in it.last and it.sent[-1][1].get("ephemeral")
    assert ac.cog.queue.qsize() == 0

    it = FakeInteraction(ac.guild, ac.channel)
    await callback(ac.cog, it, "https://youtu.be/x", "voce1", 0)
    assert ac.cog.queue.qsize() == 1
    assert ac.guild.voice_client is None        # nessuna connessione prematura: la fa il worker

    for _ in range(ai_cover_cog.MAX_QUEUE):
        ac.cog.queue.put_nowait(make_item(it))
    it = FakeInteraction(ac.guild, ac.channel)
    await callback(ac.cog, it, "https://youtu.be/x", "voce1", 0)
    assert "coda è piena" in it.last


async def run_worker(cog, *items):
    for item in items:
        cog.queue.put_nowait(item)
    cog.worker_task = asyncio.create_task(cog.queue_worker())
    await asyncio.wait_for(cog.queue.join(), 3)


async def test_worker_survives_errors_and_hides_details(ac, monkeypatch):
    outcomes = [rvc.CoverError("Video troppo lungo."),
                RuntimeError("percorso /home/segreto/token"),
                RuntimeError("HIP out of memory. Tried to allocate 2 GiB"),
                None]

    async def fake_cover(guild_id, model, url, pitch):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome
        job = rvc.create_job_dir(guild_id)
        (job / "canzone_finale.wav").write_text("x")
        return job / "canzone_finale.wav"

    monkeypatch.setattr(rvc, "ai_cover", fake_cover)
    its = [FakeInteraction(ac.guild, ac.channel, user_id=i) for i in range(4)]

    async def finish_song():
        while not (ac.guild.voice_client and ac.guild.voice_client.playing):
            await asyncio.sleep(0.01)
        ac.guild.voice_client.after(None)

    finisher = asyncio.create_task(finish_song())
    await run_worker(ac.cog, *[make_item(it) for it in its])
    await finisher

    assert any("troppo lungo" in t for t in its[0].texts())
    assert any("errore imprevisto" in t for t in its[1].texts())
    assert not any("segreto" in t for t in its[1].texts())            # nessuna fuga di dettagli
    assert any("memoria GPU esaurita" in t for t in its[2].texts())    # OOM (CUDA e ROCm)
    assert any(isinstance(c, discord.Embed) or "title" in str(k) or k.get("embed") for c, k in its[3].sent)
    assert not ac.cog.worker_task.done()                                # il worker è ancora vivo
    assert list(rvc.JOBS_DIR.iterdir()) == []                          # job ripuliti


async def test_user_who_left_voice_during_generation(ac, monkeypatch):
    it = FakeInteraction(ac.guild, ac.channel)

    async def fake_cover(guild_id, model, url, pitch):
        job = rvc.create_job_dir(guild_id)
        (job / "canzone_finale.wav").write_text("x")
        it.user.voice = None                      # l'utente esce mentre si genera
        return job / "canzone_finale.wav"

    monkeypatch.setattr(rvc, "ai_cover", fake_cover)
    await ac.cog._process(make_item(it))
    assert any("non sei più in un canale vocale" in t for t in it.texts())
    assert list(rvc.JOBS_DIR.iterdir()) == []


async def test_idle_disconnect_never_kicks_music_or_busy_worker(ac):
    vc = FakeVC(ac.channel)
    ac.guild.voice_client = vc

    vc.playing = True                              # sta suonando altro (es. musica)
    await ac.cog._idle_disconnect(ac.guild)
    assert vc.connected

    vc.playing, ac.cog._busy = False, True         # il worker sta elaborando una richiesta
    await ac.cog._idle_disconnect(ac.guild)
    assert vc.connected

    ac.cog._busy = False
    await ac.cog._idle_disconnect(ac.guild)
    assert not vc.connected


# ================================================================== tts

class FakeWav:
    def detach(self): return self
    def cpu(self): return self


class FakeModel:
    sr = 24000

    def __init__(self, error=None):
        self.error, self.thread = error, None

    def generate(self, text, audio_prompt_path, language_id):
        self.thread = threading.current_thread()
        if self.error:
            raise self.error
        return FakeWav()


@pytest.fixture
def tts(data_dir, monkeypatch):
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeSource)
    monkeypatch.setattr(TTS_COG, "ta", SimpleNamespace(save=lambda path, wav, sr: Path(path).write_bytes(b"RIFF")))
    guild = FakeGuild(7)
    channel = make_channel(guild)
    speakers = data_dir / "7" / "speakers"
    speakers.mkdir(parents=True)
    (speakers / "ref.wav").write_text("x")
    (speakers / "index.json").write_text(json.dumps({"Ref": "ref.wav"}))
    (data_dir / "secret.wav").write_text("x")
    cog = TTS_COG.TTSCog(SimpleNamespace())
    cog.device = "cpu"
    cog.model = FakeModel()
    return SimpleNamespace(cog=cog, guild=guild, channel=channel)


def tts_files():
    return set(Path(tempfile.gettempdir()).glob("tts_*.wav"))


async def test_tts_generation_does_not_block_the_event_loop(tts, tmp_path):
    out = tmp_path / "o.wav"
    assert await tts.cog.generate_audio("ciao", str(out), "ref.wav", "Ref", "it") is None
    assert out.exists()
    assert tts.cog.model.thread is not threading.main_thread()     # prima girava dentro l'event loop


async def test_tts_generation_errors_are_mapped(tts, tmp_path):
    tts.cog.model = FakeModel(RuntimeError("CUDA out of memory"))
    msg = await tts.cog.generate_audio("ciao", str(tmp_path / "o.wav"), "r", "Ref", "it")
    assert "GPU" in msg
    tts.cog.model = FakeModel(ValueError("dettagli interni"))
    msg = await tts.cog.generate_audio("ciao", str(tmp_path / "o.wav"), "r", "Ref", "it")
    assert "dettagli" not in msg and msg.startswith("❌")


async def test_tts_speak_full_flow_and_cleanup(tts):
    before = tts_files()
    it = FakeInteraction(tts.guild, tts.channel)
    await tts.cog.speak.callback(tts.cog, it, "ciao @everyone", "ref.wav", "it")
    vc = tts.guild.voice_client
    assert vc.playing
    reply = it.sent[-1]
    assert reply[0] == "🗣️ **Ref**: ciao @everyone"
    assert reply[1]["allowed_mentions"].everyone is False             # nessun ping di massa
    assert len(tts_files() - before) == 1
    vc.after(None)                                                    # fine riproduzione
    assert tts_files() == before                                      # file temporaneo rimosso


async def test_tts_speak_guards(tts):
    callback = tts.cog.speak.callback

    tts.cog.model = None
    it = FakeInteraction(tts.guild, tts.channel)
    await callback(tts.cog, it, "ciao", "ref.wav", "it")
    assert "non è pronto" in it.last
    tts.cog.model = FakeModel()

    it = FakeInteraction(tts.guild, None)
    await callback(tts.cog, it, "ciao", "ref.wav", "it")
    assert "canale vocale" in it.last

    it = FakeInteraction(tts.guild, tts.channel)
    await callback(tts.cog, it, "   ", "ref.wav", "it")
    assert "vuoto" in it.last

    for evil in ("../../secret.wav", "/etc/passwd", "nope.wav"):
        it = FakeInteraction(tts.guild, tts.channel)
        await callback(tts.cog, it, "ciao", evil, "it")
        assert "Voce non trovata" in it.last
        assert it.sent[-1][1].get("ephemeral") is True and not it.deferred   # errore privato, prima del defer
    assert tts.cog.model.thread is None                               # non ha mai generato


async def test_tts_disconnect_during_generation_and_ffmpeg_failure(tts, monkeypatch):
    before = tts_files()

    async def disconnect_midway(*args):
        tts.guild.voice_client = None
        return None

    monkeypatch.setattr(tts.cog, "generate_audio", disconnect_midway)
    it = FakeInteraction(tts.guild, tts.channel)
    await tts.cog.speak.callback(tts.cog, it, "ciao", "ref.wav", "it")
    assert "disconnesso" in it.last
    monkeypatch.delattr(tts.cog, "generate_audio")        # torna al metodo vero

    monkeypatch.setattr(discord, "FFmpegPCMAudio", lambda path: (_ for _ in ()).throw(RuntimeError("no ffmpeg")))
    tts.guild.voice_client = None
    it = FakeInteraction(tts.guild, tts.channel)
    await tts.cog.speak.callback(tts.cog, it, "ciao", "ref.wav", "it")
    assert "Impossibile riprodurre" in it.last and "no ffmpeg" not in it.last
    assert tts_files() == before                                       # nessun file orfano


async def test_tts_model_loading_failures_do_not_crash(tts, monkeypatch):
    tts.cog.model = None

    def oom():
        raise RuntimeError("HIP out of memory")

    monkeypatch.setattr(tts.cog, "_init_model_sync", oom)
    await tts.cog._async_init_model()                 # non solleva
    assert tts.cog.model is None

    monkeypatch.setattr(tts.cog, "_init_model_sync", lambda: "modello")
    await tts.cog._async_init_model()
    assert tts.cog.model == "modello"


async def test_tts_torch_load_patch_is_restored_on_unload(tts, monkeypatch):
    original = TTS_COG.torch.load
    monkeypatch.setattr(tts.cog, "_init_model_sync", lambda: "modello")
    tts.cog.original_torch_load = original
    await tts.cog._async_init_model()                 # device cpu: applica il patch
    assert TTS_COG.torch.load is not original
    await tts.cog.cog_unload()
    assert TTS_COG.torch.load is original


async def test_tts_cog_loads_without_torch_or_chatterbox(tts, monkeypatch):
    monkeypatch.setattr(TTS_COG, "ChatterboxMultilingualTTS", None)
    tts.cog.model = None
    await tts.cog._async_init_model()                 # solo un log, nessuna eccezione
    assert tts.cog.model is None
