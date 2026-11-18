"""
Voce robotica (/parla): pulizia del testo, comando di eSpeak, coda, limiti, interruzione e sintesi vera.

I test ermetici usano un finto `espeak-ng` (uno script che registra argomenti e stdin e scrive un WAV).
Quelli con il motore vero girano solo se `espeak-ng` è installato.
"""

import asyncio
import json
import shutil
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from cogs import robot_voice as rvmod
from cogs.robot_voice import (
    RobotVoice,
    SpeechError,
    build_command,
    clean_text,
    find_engine,
    synthesize,
)
from fakes import FakeGuild, FakeInteraction, FakeSource, make_channel

FAKE_ENGINE = """#!{python}
import json, os, sys, time, wave
args = sys.argv[1:]
text = sys.stdin.buffer.read().decode("utf-8")
with open(os.environ["FAKE_ESPEAK_LOG"], "a") as f:
    f.write(json.dumps({{"argv": args, "stdin": text}}) + "\\n")
modes_file = os.environ.get("FAKE_ESPEAK_MODES")
mode = "ok"
if modes_file and os.path.exists(modes_file):
    modes = open(modes_file).read().split()
    if modes:
        mode = modes.pop(0)
        open(modes_file, "w").write(" ".join(modes))
if mode == "fail":
    sys.stderr.write("errore finto")
    sys.exit(1)
if mode == "slow":
    time.sleep(30)
if mode == "nofile":
    sys.exit(0)
out = args[args.index("-w") + 1]
with wave.open(out, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
    w.writeframes(b"\\x01\\x01" * 2205)
"""


async def wait_until(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condizione non raggiunta in tempo")
        await asyncio.sleep(0.01)


@pytest.fixture
async def rv(tmp_path, monkeypatch):
    log = tmp_path / "espeak.log"
    script = tmp_path / "fake-espeak"
    script.write_text(FAKE_ENGINE.format(python=sys.executable))
    script.chmod(0o755)
    modes = tmp_path / "modes"
    monkeypatch.setenv("ESPEAK_PATH", str(script))
    monkeypatch.setenv("FAKE_ESPEAK_LOG", str(log))
    monkeypatch.setenv("FAKE_ESPEAK_MODES", str(modes))
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeSource)
    guild = FakeGuild(7)
    channel = make_channel(guild)
    cog = RobotVoice(SimpleNamespace(user=SimpleNamespace(id=999)))

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    yield SimpleNamespace(
        cog=cog, guild=guild, channel=channel, calls=calls, script=script,
        set_modes=lambda *m: modes.write_text(" ".join(m)),
    )
    await cog.cog_unload()


async def say(rv, text="ciao a tutti", user_id=42, name="alice", channel="default", **options):
    channel = rv.channel if channel == "default" else channel
    it = FakeInteraction(rv.guild, channel, user_id=user_id, name=name)
    await rv.cog.parla.callback(
        rv.cog, it, text, options.get("voce"), options.get("velocita"), options.get("lingua")
    )
    return it


def vc_of(rv):
    return rv.guild.voice_client


def end_playback(rv):
    """Come discord.py a fine riproduzione: is_playing() torna False e viene chiamato `after`."""
    vc = vc_of(rv)
    after = vc.after
    vc.playing, vc.source = False, None
    after(None)


async def finish_current(rv):
    """Fa terminare il messaggio che il bot sta leggendo."""
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    end_playback(rv)


# ===================================================================== pulizia del testo

class FakeMember:
    display_name = "Mario"


class FakeTextGuild:
    def get_member(self, user_id):
        return FakeMember() if user_id == 123 else None

    def get_role(self, role_id):
        return SimpleNamespace(name="Moderatori") if role_id == 5 else None

    def get_channel(self, channel_id):
        return SimpleNamespace(name="generale") if channel_id == 9 else None


@pytest.mark.parametrize("raw, expected", [
    ("ciao a tutti", "ciao a tutti"),
    ("  molti   spazi \n\n e a capo  ", "molti spazi e a capo"),
    ("**grassetto** _corsivo_ ~~barrato~~ `codice` ||spoiler||", "grassetto corsivo barrato codice spoiler"),
    ("> citazione\n# titolo", "citazione titolo"),
    ("guarda https://example.com/molto/lungo?x=1 ora", "guarda link ora"),
    ("ehi <@123> e <@!123> e <@999>", "ehi Mario e Mario e qualcuno"),
    ("per <@&5> in <#9>, non <@&6> o <#1>", "per Moderatori in generale, non un ruolo o un canale"),
    ("evviva <:festa:123456789> e <a:ballo:987654321>", "evviva festa e ballo"),
    ("con\x00controllo\x07 e\u200bzero-width", "con controllo e zero-width"),
    ("snake_case_name", "snake case name"),
    ("***", ""),
    ("   \n\t ", ""),
])
def test_clean_text(raw, expected):
    assert clean_text(raw, FakeTextGuild()) == expected


@pytest.mark.parametrize("text, readable", [
    ("ciao", True), ("123", True), ("😀", True), ("sì!", True), ("ok...", True),
    ("", False), (".", False), ("...", False), ("?!", False), ("- - -", False), ("()", False),
])
def test_is_readable(text, readable):
    assert rvmod.is_readable(text) is readable


def test_clean_text_works_without_a_guild():
    assert clean_text("ciao <@123> <#9>") == "ciao qualcuno un canale"


# ============================================================================ il motore

def test_command_line_never_contains_the_text_and_follows_the_presets():
    cmd = build_command("/usr/bin/espeak-ng", "/tmp/o.wav", "it", "robot", "normale")
    assert cmd == ["/usr/bin/espeak-ng", "-v", "it", "-s", "160", "-p", "50", "-a", "150", "-w", "/tmp/o.wav", "--stdin"]

    cmd = build_command("e", "o.wav", "en", "grave", "veloce")
    assert cmd[cmd.index("-v") + 1] == "en+m3" and cmd[cmd.index("-s") + 1] == "210" and cmd[cmd.index("-p") + 1] == "25"
    assert build_command("e", "o", "pt", "acuta", "lenta")[2] == "pt-br+f3"
    assert build_command("e", "o", "it", "sussurro", "normale")[2] == "it+whisper"
    # valori sconosciuti: si usano quelli predefiniti, mai un errore
    assert build_command("e", "o", "xx", "boh", "boh")[1:8] == ["-v", "it", "-s", "160", "-p", "50", "-a"]


def test_find_engine(tmp_path, monkeypatch):
    monkeypatch.delenv("ESPEAK_PATH", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name == "espeak" else None)
    assert find_engine() == "/usr/bin/espeak"                                   # ripiega sul vecchio espeak
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert find_engine() == "/usr/bin/espeak-ng"                                # preferisce espeak-ng
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_engine() is None
    monkeypatch.setenv("ESPEAK_PATH", "/opt/mio/espeak-ng")
    monkeypatch.setattr(shutil, "which", lambda name: name if name == "/opt/mio/espeak-ng" else None)
    assert find_engine() == "/opt/mio/espeak-ng"


async def test_synthesize_passes_the_text_through_stdin(rv, tmp_path):
    out = tmp_path / "o.wav"
    hostile = "--version; rm -rf / $(whoami) `id` \"'"
    await synthesize(find_engine(), hostile, str(out), "it", "robot", "normale")
    call = rv.calls()[0]
    assert call["stdin"] == hostile + "\n"                       # il testo arriva intatto da stdin...
    assert hostile not in " ".join(call["argv"]) and "--version" not in call["argv"]   # ...mai come argomento
    with wave.open(str(out)) as w:
        assert w.getframerate() == 22050 and w.getnframes() > 0


async def test_synthesize_errors_are_mapped(rv, tmp_path, monkeypatch):
    engine = find_engine()
    rv.set_modes("fail")
    with pytest.raises(SpeechError, match="non è riuscito"):
        await synthesize(engine, "ciao", str(tmp_path / "a.wav"), "it", "robot", "normale")

    rv.set_modes("nofile")                                        # eSpeak esce con 0 senza scrivere nulla
    with pytest.raises(SpeechError, match="niente da leggere"):
        await synthesize(engine, "ciao", str(tmp_path / "b.wav"), "it", "robot", "normale")

    rv.set_modes("slow")
    monkeypatch.setattr(rvmod, "SYNTH_TIMEOUT", 0.3)
    with pytest.raises(SpeechError, match="troppo"):
        await synthesize(engine, "ciao", str(tmp_path / "c.wav"), "it", "robot", "normale")

    with pytest.raises(SpeechError, match="non si avvia"):
        await synthesize(str(tmp_path / "non-esiste"), "ciao", str(tmp_path / "d.wav"), "it", "robot", "normale")


# ========================================================================= il comando

async def test_speaks_in_the_users_channel_and_shows_the_text(rv):
    it = await say(rv, "ciao a tutti")
    assert it.sent[0][0] == "🤖 **alice**: ciao a tutti"
    assert it.sent[0][1]["allowed_mentions"].everyone is False and it.sent[0][1]["allowed_mentions"].users is False

    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    wav = Path(vc_of(rv).played[0].url)
    assert wav.exists() and wav.suffix == ".wav"                # il file esiste mentre suona...
    assert rv.calls()[0]["stdin"] == "ciao a tutti\n"
    argv = rv.calls()[0]["argv"]
    assert argv[argv.index("-v") + 1] == "it" and argv[argv.index("-s") + 1] == "160"

    end_playback(rv)
    await wait_until(lambda: not wav.exists())                  # ...e viene eliminato a fine riproduzione
    state = rv.cog.guilds[7]
    await wait_until(lambda: not state.active and state.idle_task is not None)   # poi parte il timer di inattività


async def test_voice_speed_and_language_options(rv):
    await say(rv, "hello", voce="grave", velocita="veloce", lingua="en")
    await wait_until(lambda: rv.calls())
    argv = rv.calls()[0]["argv"]
    assert argv[argv.index("-v") + 1] == "en+m3" and argv[argv.index("-s") + 1] == "210" and argv[argv.index("-p") + 1] == "25"


async def test_text_is_cleaned_before_being_shown_and_read(rv):
    it = await say(rv, "**ciao** <@123> guarda https://x.it/y @everyone")
    assert it.sent[0][0] == "🤖 **alice**: ciao qualcuno guarda link @everyone"
    await wait_until(lambda: rv.calls())
    assert rv.calls()[0]["stdin"] == "ciao qualcuno guarda link @everyone\n"
    assert it.sent[0][1]["allowed_mentions"].everyone is False   # @everyone non notifica nessuno


async def test_names_cannot_break_the_formatting(rv):
    it = await say(rv, "ciao", name="**boss**_x")
    assert it.sent[0][0] == "🤖 **\\*\\*boss\\*\\*\\_x**: ciao"


async def test_messages_are_read_in_order_and_the_waiting_user_sees_the_queue(rv):
    first = await say(rv, "primo", user_id=1, name="anna")
    second = await say(rv, "secondo", user_id=2, name="bruno")
    assert "In coda" not in first.sent[0][0] and "In coda (posizione 2)" in second.sent[0][0]

    await finish_current(rv)                                    # finito "primo": passa a "secondo"
    await wait_until(lambda: len(vc_of(rv).played) == 2 and vc_of(rv).playing)
    assert [c["stdin"] for c in rv.calls()] == ["primo\n", "secondo\n"]
    end_playback(rv)
    await wait_until(lambda: not rv.cog.guilds[7].active)


async def test_per_user_and_per_server_limits(rv, monkeypatch):
    # "bloccato": il primo messaggio resta in lettura finché non lo si fa terminare
    await say(rv, "uno", user_id=1)
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    for n in range(rvmod.MAX_PER_USER):
        assert "In coda" in (await say(rv, f"mio {n}", user_id=2)).sent[0][0]
    blocked = await say(rv, "troppi", user_id=2)
    assert f"{rvmod.MAX_PER_USER} messaggi in coda" in blocked.last and blocked.sent[-1][1]["ephemeral"] is True

    monkeypatch.setattr(rvmod, "MAX_QUEUE", len(rv.cog.guilds[7].queue))
    full = await say(rv, "pieno", user_id=3)
    assert "troppi messaggi in coda" in full.last and full.sent[-1][1]["ephemeral"] is True


async def test_errors_are_private_and_nothing_is_said_publicly(rv, monkeypatch):
    # fuori dalla vocale
    it = await say(rv, "ciao", channel=None)
    assert "canale vocale" in it.last and it.sent[0][1]["ephemeral"] is True and len(it.sent) == 1

    # niente da leggere dopo la pulizia, o solo punteggiatura: il bot non deve entrare in vocale per tacere
    for nothing in ("***", "...", "?! ...", "- - -"):
        it = await say(rv, nothing)
        assert "niente da leggere" in it.last and it.sent[0][1]["ephemeral"] is True, nothing
    assert vc_of(rv) is None and rv.calls() == []

    # motore non installato: l'utente riceve istruzioni, il bot non crasha
    monkeypatch.setenv("ESPEAK_PATH", "/non/esiste/espeak-ng")
    it = await say(rv, "ciao")
    assert "espeak-ng" in it.last and "installarlo" in it.last and it.sent[0][1]["ephemeral"] is True
    assert vc_of(rv) is None and rv.calls() == []


async def test_does_not_interrupt_other_audio_or_speak_in_two_channels(rv):
    vc = await rv.channel.connect()
    vc.playing, vc.source = True, object()                       # musica / AI cover in corso
    it = await say(rv, "ciao")
    assert "altro audio" in it.last and it.sent[0][1]["ephemeral"] is True and rv.calls() == []
    vc.playing, vc.source = False, None

    await say(rv, "primo", user_id=1)
    await wait_until(lambda: vc.playing)
    elsewhere = await say(rv, "ciao", user_id=2, channel=make_channel(rv.guild, "altro"))
    assert "altro canale vocale" in elsewhere.last and elsewhere.sent[0][1]["ephemeral"] is True


async def test_user_who_left_the_voice_channel_gets_a_private_warning(rv):
    await say(rv, "primo", user_id=1)
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    leaver = await say(rv, "secondo", user_id=2)
    leaver.user.voice = None                                     # esce mentre aspetta il suo turno
    end_playback(rv)
    await wait_until(lambda: len(leaver.sent) == 2)
    assert "Non sei più in un canale vocale" in leaver.last and leaver.sent[-1][1]["ephemeral"] is True
    assert [c["stdin"] for c in rv.calls()] == ["primo\n"]       # il suo messaggio non è stato letto


async def test_a_synthesis_failure_is_reported_privately_and_the_queue_goes_on(rv):
    rv.set_modes("fail", "ok")
    broken = await say(rv, "primo", user_id=1)
    fine = await say(rv, "secondo", user_id=2)
    await wait_until(lambda: len(broken.sent) == 2)
    assert "❌" in broken.last and broken.sent[-1][1]["ephemeral"] is True
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)   # "secondo" viene letto lo stesso
    assert len(fine.sent) == 1
    end_playback(rv)


async def test_unexpected_playback_errors_do_not_kill_the_worker(rv, monkeypatch):
    def boom(path):
        raise RuntimeError("ffmpeg non trovato")

    monkeypatch.setattr(discord, "FFmpegPCMAudio", boom)
    it = await say(rv, "ciao")
    await wait_until(lambda: len(it.sent) == 2)
    assert "FFmpeg" in it.last and "ffmpeg non trovato" not in it.last      # nessun dettaglio interno
    await wait_until(lambda: not rv.cog.guilds[7].active)


# ================================================================== /parla-stop e pulizia

async def test_stop_interrupts_the_speech_and_clears_the_queue(rv):
    await say(rv, "primo", user_id=1)
    await say(rv, "secondo", user_id=2)
    await say(rv, "terzo", user_id=3)
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)

    it = FakeInteraction(rv.guild, rv.channel, user_id=2)
    await rv.cog.parla_stop.callback(rv.cog, it)
    assert "interrotta" in it.last and "2 messaggi in coda eliminati" in it.last
    await wait_until(lambda: not vc_of(rv).playing and not rv.cog.guilds[7].active)
    assert [c["stdin"] for c in rv.calls()] == ["primo\n"]       # gli altri non vengono letti


async def test_stop_guards(rv):
    it = FakeInteraction(rv.guild, rv.channel)
    await rv.cog.parla_stop.callback(rv.cog, it)
    assert "non sta parlando" in it.last and it.sent[0][1]["ephemeral"] is True

    await say(rv, "ciao")
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    outsider = FakeInteraction(rv.guild, make_channel(rv.guild, "altro"), user_id=9)
    await rv.cog.parla_stop.callback(rv.cog, outsider)
    assert "stesso canale" in outsider.last and vc_of(rv).playing    # chi è altrove non può zittire il bot


async def test_a_message_sent_right_after_stop_is_not_lost(rv):
    """Se /parla arriva mentre il worker viene fermato, il messaggio non deve restare in coda per sempre."""
    await say(rv, "vecchio", user_id=1)
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    stop = FakeInteraction(rv.guild, rv.channel, user_id=1)
    await rv.cog.parla_stop.callback(rv.cog, stop)
    await say(rv, "nuovo", user_id=2)                            # subito dopo, prima che il worker sia davvero finito
    await wait_until(lambda: [c["stdin"] for c in rv.calls()] == ["vecchio\n", "nuovo\n"])
    await wait_until(lambda: vc_of(rv).playing and len(vc_of(rv).played) == 2)


async def test_leaves_the_voice_channel_after_a_minute_of_silence(rv, monkeypatch):
    monkeypatch.setattr(rvmod, "IDLE_TIMEOUT", 0.05)
    await say(rv, "ciao")
    await finish_current(rv)
    vc = vc_of(rv)
    await wait_until(lambda: not vc.connected)

    # ...ma non se nel frattempo subentra altro audio
    vc2 = await rv.channel.connect()
    await say(rv, "ancora")
    await finish_current(rv)
    await wait_until(lambda: not rv.cog.guilds[7].active)
    vc2.playing, vc2.source = True, object()
    await asyncio.sleep(0.2)
    assert vc2.connected


async def test_bot_disconnection_clears_everything(rv):
    await say(rv, "primo", user_id=1)
    await say(rv, "secondo", user_id=2)
    await wait_until(lambda: vc_of(rv) is not None and vc_of(rv).playing)
    state = rv.cog.guilds[7]
    bot_member = SimpleNamespace(id=999, guild=rv.guild)
    await rv.cog.on_voice_state_update(bot_member, SimpleNamespace(channel=rv.channel), SimpleNamespace(channel=None))
    assert 7 not in rv.cog.guilds
    await wait_until(lambda: state.worker is None or state.worker.done())


def test_command_has_a_per_user_cooldown_and_sane_options():
    assert len(rv_command().checks) == 1                           # il cooldown: l'errore lo gestisce main.py
    params = {p.name: p for p in rv_command().parameters}
    assert params["testo"].required and params["testo"].max_value == rvmod.MAX_CHARS
    assert [c.value for c in params["voce"].choices] == ["robot", "grave", "acuta", "sussurro"]
    assert [c.value for c in params["velocita"].choices] == ["lenta", "normale", "veloce"]
    assert [c.value for c in params["lingua"].choices] == ["it", "en", "es", "fr", "de", "pt"]
    assert not any(params[n].required for n in ("voce", "velocita", "lingua"))


def rv_command():
    return RobotVoice(SimpleNamespace()).parla


# ==================================================================== motore VERO (se c'è)

real_engine = pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng non installato")


@real_engine
@pytest.mark.parametrize("language", list(rvmod.LANGUAGES))
@pytest.mark.parametrize("voice", list(rvmod.VOICES))
async def test_real_engine_speaks_every_language_and_voice(tmp_path, monkeypatch, language, voice):
    monkeypatch.delenv("ESPEAK_PATH", raising=False)
    out = tmp_path / "o.wav"
    await synthesize(find_engine(), "ciao a tutti, questa è una prova", str(out), language, voice, "normale")
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 22050 and w.getnframes() > 5000


@real_engine
async def test_real_engine_speed_changes_the_duration(tmp_path, monkeypatch):
    monkeypatch.delenv("ESPEAK_PATH", raising=False)
    durations = {}
    for speed in rvmod.SPEEDS:
        out = tmp_path / f"{speed}.wav"
        await synthesize(find_engine(), "questa è una frase abbastanza lunga per misurare la velocità", str(out), "it", "robot", speed)
        with wave.open(str(out)) as w:
            durations[speed] = w.getnframes() / w.getframerate()
    assert durations["lenta"] > durations["normale"] > durations["veloce"]


@real_engine
async def test_real_engine_handles_hostile_and_empty_text(tmp_path, monkeypatch):
    monkeypatch.delenv("ESPEAK_PATH", raising=False)
    out = tmp_path / "h.wav"
    await synthesize(find_engine(), "--version -h $(id) `id`", str(out), "it", "robot", "normale")
    assert out.stat().st_size > 5000                               # letto come testo, non preso per opzioni

    for nothing in ("", "   ", "\n\t"):                              # eSpeak scrive un WAV di 352 byte: silenzio
        with pytest.raises(SpeechError, match="niente da leggere"):
            await synthesize(find_engine(), nothing, str(tmp_path / "vuoto.wav"), "it", "robot", "normale")


@real_engine
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg non installato")
async def test_real_engine_output_is_playable_by_discord_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.delenv("ESPEAK_PATH", raising=False)
    out = tmp_path / "play.wav"
    await synthesize(find_engine(), "prova di riproduzione", str(out), "it", "robot", "normale")
    source = discord.FFmpegPCMAudio(str(out))                      # esattamente ciò che usa il bot
    try:
        frames = []
        while True:
            frame = source.read()                                  # 20ms di PCM a 48kHz stereo
            if not frame:
                break
            frames.append(frame)
    finally:
        source.cleanup()
    assert len(frames) > 20 and all(len(f) == 3840 for f in frames[:-1])
    assert any(any(f) for f in frames)                             # non è silenzio
