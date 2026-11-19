"""
TTS con la voce Giorgio locale (/tts): comando, coda, limiti, interruzione e motore.

I test del cog usano un motore finto. Quelli del motore usano un finto modulo `pyttsx3`.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from cogs import local_tts as pt
from cogs.local_tts import LocalEngine, LocalTTS, SpeechError, clean_text
from fakes import FakeGuild, FakeInteraction, FakeSource, make_channel


async def wait_until(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condizione non raggiunta in tempo")
        await asyncio.sleep(0.01)


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
    ("con\x00controllo\x07 e​zero-width", "con controllo e zero-width"),
    ("snake_case_name", "snake case name"),
    ("***", ""),
    ("   \n\t ", ""),
])
def test_clean_text(raw, expected):
    assert clean_text(raw, FakeTextGuild()) == expected


def test_clean_text_works_without_a_guild():
    assert clean_text("ciao <@123> <#9>") == "ciao qualcuno un canale"


@pytest.mark.parametrize("text, readable", [
    ("ciao", True), ("123", True), ("😀", True), ("sì!", True), ("ok...", True),
    ("", False), (".", False), ("...", False), ("?!", False), ("- - -", False), ("()", False),
])
def test_is_readable(text, readable):
    assert pt.is_readable(text) is readable


# ============================================================================ il comando

class FakeEngine:
    """Motore finto per i test del cog: registra i testi e può fallire."""

    def __init__(self):
        self.texts = []
        self.problem_text = None
        self.modes = []                  # "fail" per far fallire la prossima sintesi

    async def problem(self):
        return self.problem_text

    async def synthesize(self, text, path):
        self.texts.append(text)
        if self.modes and self.modes.pop(0) == "fail":
            raise SpeechError("errore finto")
        with open(path, "wb") as f:
            f.write(b"WAVDATA")


@pytest.fixture
async def tts(monkeypatch):
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeSource)
    guild = FakeGuild(7)
    channel = make_channel(guild)
    cog = LocalTTS(SimpleNamespace(user=SimpleNamespace(id=999)))
    cog.engine = FakeEngine()
    yield SimpleNamespace(cog=cog, guild=guild, channel=channel, engine=cog.engine)
    await cog.cog_unload()


async def say(t, text="ciao a tutti", user_id=42, name="alice", channel="default"):
    channel = t.channel if channel == "default" else channel
    it = FakeInteraction(t.guild, channel, user_id=user_id, name=name)
    await t.cog.tts.callback(t.cog, it, text)
    return it


def vc_of(t):
    return t.guild.voice_client


def end_playback(t):
    """Come discord.py a fine riproduzione: is_playing() torna False e viene chiamato `after`."""
    vc = vc_of(t)
    after = vc.after
    vc.playing, vc.source = False, None
    after(None)


async def finish_current(t):
    await wait_until(lambda: vc_of(t) is not None and vc_of(t).playing)
    end_playback(t)


async def test_speaks_in_the_users_channel_and_shows_the_text(tts):
    it = await say(tts, "ciao a tutti")
    assert it.sent[0][0] == "🗣️ **alice**: ciao a tutti"
    assert it.sent[0][1]["allowed_mentions"].everyone is False and it.sent[0][1]["allowed_mentions"].users is False

    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)
    wav = Path(vc_of(tts).played[0].url)
    assert wav.suffix == ".wav" and wav.read_bytes() == b"WAVDATA"      # il file esiste mentre suona...
    assert tts.engine.texts == ["ciao a tutti"]

    end_playback(tts)
    await wait_until(lambda: not wav.exists())                           # ...e viene eliminato a fine riproduzione
    state = tts.cog.guilds[7]
    await wait_until(lambda: not state.active and state.idle_task is not None)   # poi parte il timer di inattività


async def test_text_is_cleaned_before_being_shown_and_read(tts):
    it = await say(tts, "**ciao** <@123> guarda https://x.it/y @everyone")
    assert it.sent[0][0] == "🗣️ **alice**: ciao qualcuno guarda link @everyone"
    await wait_until(lambda: tts.engine.texts)
    assert tts.engine.texts == ["ciao qualcuno guarda link @everyone"]
    assert it.sent[0][1]["allowed_mentions"].everyone is False           # @everyone non notifica nessuno


async def test_names_cannot_break_the_formatting(tts):
    it = await say(tts, "ciao", name="**boss**_x")
    assert it.sent[0][0] == "🗣️ **\\*\\*boss\\*\\*\\_x**: ciao"


async def test_messages_are_read_in_order_and_the_waiting_user_sees_the_queue(tts):
    first = await say(tts, "primo", user_id=1, name="anna")
    second = await say(tts, "secondo", user_id=2, name="bruno")
    assert "In coda" not in first.sent[0][0] and "In coda (posizione 2)" in second.sent[0][0]

    await finish_current(tts)                                    # finito "primo": passa a "secondo"
    await wait_until(lambda: len(vc_of(tts).played) == 2 and vc_of(tts).playing)
    assert tts.engine.texts == ["primo", "secondo"]
    end_playback(tts)
    await wait_until(lambda: not tts.cog.guilds[7].active)


async def test_per_user_and_per_server_limits(tts, monkeypatch):
    await say(tts, "uno", user_id=1)
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)
    for n in range(pt.MAX_PER_USER):
        assert "In coda" in (await say(tts, f"mio {n}", user_id=2)).sent[0][0]
    blocked = await say(tts, "troppi", user_id=2)
    assert f"{pt.MAX_PER_USER} messaggi in coda" in blocked.last and blocked.sent[-1][1]["ephemeral"] is True

    monkeypatch.setattr(pt, "MAX_QUEUE", len(tts.cog.guilds[7].queue))
    full = await say(tts, "pieno", user_id=3)
    assert "troppi messaggi in coda" in full.last and full.sent[-1][1]["ephemeral"] is True


async def test_errors_are_private_and_nothing_is_said_publicly(tts):
    it = await say(tts, "ciao", channel=None)                    # fuori dalla vocale
    assert "canale vocale" in it.last and it.sent[0][1]["ephemeral"] is True and len(it.sent) == 1

    # niente da leggere dopo la pulizia, o solo punteggiatura: il bot non deve entrare in vocale per tacere
    for nothing in ("***", "...", "?! ...", "- - -"):
        it = await say(tts, nothing)
        assert "niente da leggere" in it.last and it.sent[0][1]["ephemeral"] is True, nothing
    assert vc_of(tts) is None and tts.engine.texts == []


async def test_missing_configuration_is_explained_privately_and_nothing_breaks(tts):
    tts.engine.problem_text = "La libreria `pyttsx3` non è installata."
    it = await say(tts, "ciao")
    assert "non è configurato" in it.last and "pyttsx3" in it.last
    assert it.sent[0][1]["ephemeral"] is True and vc_of(tts) is None and tts.engine.texts == []


async def test_does_not_interrupt_other_audio_or_speak_in_two_channels(tts):
    vc = await tts.channel.connect()
    vc.playing, vc.source = True, object()                       # musica / AI cover in corso
    it = await say(tts, "ciao")
    assert "altro audio" in it.last and it.sent[0][1]["ephemeral"] is True and tts.engine.texts == []
    vc.playing, vc.source = False, None

    await say(tts, "primo", user_id=1)
    await wait_until(lambda: vc.playing)
    elsewhere = await say(tts, "ciao", user_id=2, channel=make_channel(tts.guild, "altro"))
    assert "altro canale vocale" in elsewhere.last and elsewhere.sent[0][1]["ephemeral"] is True


async def test_user_who_left_the_voice_channel_gets_a_private_warning(tts):
    await say(tts, "primo", user_id=1)
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)
    leaver = await say(tts, "secondo", user_id=2)
    leaver.user.voice = None                                     # esce mentre aspetta il suo turno
    end_playback(tts)
    await wait_until(lambda: len(leaver.sent) == 2)
    assert "Non sei più in un canale vocale" in leaver.last and leaver.sent[-1][1]["ephemeral"] is True
    assert tts.engine.texts == ["primo"]                         # il suo messaggio non è stato letto


async def test_a_synthesis_failure_is_reported_privately_and_the_queue_goes_on(tts):
    tts.engine.modes = ["fail", "ok"]
    broken = await say(tts, "primo", user_id=1)
    fine = await say(tts, "secondo", user_id=2)
    await wait_until(lambda: len(broken.sent) == 2)
    assert "❌ errore finto" in broken.last and broken.sent[-1][1]["ephemeral"] is True
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)   # "secondo" viene letto lo stesso
    assert len(fine.sent) == 1
    end_playback(tts)


async def test_unexpected_playback_errors_do_not_kill_the_worker(tts, monkeypatch):
    def boom(path):
        raise RuntimeError("ffmpeg non trovato")

    monkeypatch.setattr(discord, "FFmpegPCMAudio", boom)
    it = await say(tts, "ciao")
    await wait_until(lambda: len(it.sent) == 2)
    assert "FFmpeg" in it.last and "ffmpeg non trovato" not in it.last      # nessun dettaglio interno
    await wait_until(lambda: not tts.cog.guilds[7].active)


# ================================================================== /tts-stop e pulizia

async def test_stop_interrupts_the_speech_and_clears_the_queue(tts):
    await say(tts, "primo", user_id=1)
    await say(tts, "secondo", user_id=2)
    await say(tts, "terzo", user_id=3)
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)

    it = FakeInteraction(tts.guild, tts.channel, user_id=2)
    await tts.cog.tts_stop.callback(tts.cog, it)
    assert "interrotta" in it.last and "2 messaggi in coda eliminati" in it.last
    await wait_until(lambda: not vc_of(tts).playing and not tts.cog.guilds[7].active)
    assert tts.engine.texts == ["primo"]                         # gli altri non vengono letti


async def test_stop_guards(tts):
    it = FakeInteraction(tts.guild, tts.channel)
    await tts.cog.tts_stop.callback(tts.cog, it)
    assert "non sta parlando" in it.last and it.sent[0][1]["ephemeral"] is True

    await say(tts, "ciao")
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)
    outsider = FakeInteraction(tts.guild, make_channel(tts.guild, "altro"), user_id=9)
    await tts.cog.tts_stop.callback(tts.cog, outsider)
    assert "stesso canale" in outsider.last and vc_of(tts).playing    # chi è altrove non può zittire il bot


async def test_a_message_sent_right_after_stop_is_not_lost(tts):
    """Se /tts arriva mentre il worker viene fermato, il messaggio non deve restare in coda per sempre."""
    await say(tts, "vecchio", user_id=1)
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)
    stop = FakeInteraction(tts.guild, tts.channel, user_id=1)
    await tts.cog.tts_stop.callback(tts.cog, stop)
    await say(tts, "nuovo", user_id=2)                           # subito dopo, prima che il worker sia davvero finito
    await wait_until(lambda: tts.engine.texts == ["vecchio", "nuovo"])
    await wait_until(lambda: vc_of(tts).playing and len(vc_of(tts).played) == 2)


async def test_leaves_the_voice_channel_after_a_minute_of_silence(tts, monkeypatch):
    monkeypatch.setattr(pt, "IDLE_TIMEOUT", 0.05)
    await say(tts, "ciao")
    await finish_current(tts)
    vc = vc_of(tts)
    await wait_until(lambda: not vc.connected)

    # ...ma non se nel frattempo subentra altro audio
    vc2 = await tts.channel.connect()
    await say(tts, "ancora")
    await finish_current(tts)
    await wait_until(lambda: not tts.cog.guilds[7].active)
    vc2.playing, vc2.source = True, object()
    await asyncio.sleep(0.2)
    assert vc2.connected


async def test_bot_disconnection_clears_everything(tts):
    await say(tts, "primo", user_id=1)
    await say(tts, "secondo", user_id=2)
    await wait_until(lambda: vc_of(tts) is not None and vc_of(tts).playing)
    state = tts.cog.guilds[7]
    bot_member = SimpleNamespace(id=999, guild=tts.guild)
    await tts.cog.on_voice_state_update(bot_member, SimpleNamespace(channel=tts.channel), SimpleNamespace(channel=None))
    assert 7 not in tts.cog.guilds
    await wait_until(lambda: state.worker is None or state.worker.done())


def test_command_has_a_per_user_cooldown_and_a_single_option():
    command = LocalTTS(SimpleNamespace()).tts
    assert len(command.checks) == 1                                # il cooldown: l'errore lo gestisce main.py
    params = {p.name: p for p in command.parameters}
    assert list(params) == ["testo"] and params["testo"].required and params["testo"].max_value == pt.MAX_CHARS


# ================================================================ motore: finto pyttsx3

class FakePyttsx3:
    """Finto modulo pyttsx3: registra proprietà e testo, scrive un WAV finto."""

    def __init__(self, voices, audio=b"RIFFfake"):
        self.voices = [SimpleNamespace(name=n, id=f"id-{n}") for n in voices]
        self.audio = audio
        self.props = {}
        self.said = []

    def init(self):
        return self

    def getProperty(self, name):
        return self.voices

    def setProperty(self, name, value):
        self.props[name] = value

    def save_to_file(self, text, path):
        self.said.append(text)
        self._path = path

    def runAndWait(self):
        with open(self._path, "wb") as f:
            f.write(self.audio)


@pytest.fixture
def pyttsx3(monkeypatch):
    fake = FakePyttsx3(["Elsa", "Microsoft Giorgio Desktop"])
    monkeypatch.setitem(sys.modules, "pyttsx3", fake)
    return fake


async def test_picks_the_giorgio_voice_and_writes_the_audio(pyttsx3, tmp_path):
    path = tmp_path / "out.wav"
    await LocalEngine().synthesize("ciao", str(path))
    assert path.read_bytes() == b"RIFFfake" and pyttsx3.said == ["ciao"]
    assert pyttsx3.props == {"voice": "id-Microsoft Giorgio Desktop", "rate": pt.RATE, "volume": 1.0}


async def test_missing_voice_is_explained_and_lists_the_installed_ones(pyttsx3, tmp_path, caplog):
    pyttsx3.voices = pyttsx3.voices[:1]
    with pytest.raises(SpeechError, match="Giorgio"):
        await LocalEngine().synthesize("ciao", str(tmp_path / "out.wav"))
    assert "Elsa" in caplog.text


async def test_empty_audio_is_an_error(pyttsx3, tmp_path):
    pyttsx3.audio = b""
    with pytest.raises(SpeechError, match="nessun audio"):
        await LocalEngine().synthesize("ciao", str(tmp_path / "out.wav"))


async def test_engine_crash_does_not_leak_details(pyttsx3, tmp_path):
    pyttsx3.runAndWait = lambda: 1 / 0
    with pytest.raises(SpeechError) as e:
        await LocalEngine().synthesize("ciao", str(tmp_path / "out.wav"))
    assert "division" not in str(e.value)


async def test_without_pyttsx3_the_bot_still_starts_and_explains(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pyttsx3", None)          # import -> ImportError
    monkeypatch.setattr(pt.importlib.util, "find_spec", lambda name: None)
    engine = LocalEngine()
    assert "pip install pyttsx3" in await engine.problem()
    with pytest.raises(SpeechError, match="pyttsx3"):
        await engine.synthesize("ciao", str(tmp_path / "out.wav"))
