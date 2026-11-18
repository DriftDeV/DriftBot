"""
TTS con la voce Giorgio di Amazon Polly (/tts): comando, coda, limiti, interruzione e motore.

I test del cog usano un motore finto. Quelli del motore usano il VERO boto3 contro un finto server Polly
(stesso formato REST/JSON e firma AWS SigV4), così si verificano richiesta, firma ed errori come li vedrebbe AWS.
"""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from aiohttp.test_utils import TestServer

from cogs import polly_tts as pt
from cogs.polly_tts import PollyConfig, PollyEngine, PollyTTS, SpeechError, clean_text
from fake_servers import FakePolly
from fakes import FakeGuild, FakeInteraction, FakeSource, make_channel

ACCESS_KEY = "AKIATESTKEY1234567890"
SECRET_KEY = "segretissima/chiave+di+prova/0123456789abcdef"


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
    """Motore finto per i test del cog: registra i testi e può fallire o avere un tetto di spesa."""

    def __init__(self):
        self.texts = []
        self.problem_text = None
        self.remaining_value = None
        self.modes = []                  # "fail" per far fallire la prossima sintesi
        self.closed = False

    async def problem(self):
        return self.problem_text

    def remaining(self):
        return self.remaining_value

    async def synthesize(self, text):
        self.texts.append(text)
        if self.modes and self.modes.pop(0) == "fail":
            raise SpeechError("errore finto")
        return b"MP3DATA"

    async def close(self):
        self.closed = True


@pytest.fixture
async def tts(monkeypatch):
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeSource)
    guild = FakeGuild(7)
    channel = make_channel(guild)
    cog = PollyTTS(SimpleNamespace(user=SimpleNamespace(id=999)), PollyConfig())
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
    mp3 = Path(vc_of(tts).played[0].url)
    assert mp3.suffix == ".mp3" and mp3.read_bytes() == b"MP3DATA"      # il file esiste mentre suona...
    assert tts.engine.texts == ["ciao a tutti"]

    end_playback(tts)
    await wait_until(lambda: not mp3.exists())                           # ...e viene eliminato a fine riproduzione
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
    tts.engine.problem_text = "Mancano le credenziali AWS: imposta AWS_ACCESS_KEY_ID."
    it = await say(tts, "ciao")
    assert "non è configurato" in it.last and "AWS_ACCESS_KEY_ID" in it.last
    assert it.sent[0][1]["ephemeral"] is True and vc_of(tts) is None and tts.engine.texts == []


async def test_daily_budget_exhausted_is_reported_privately(tts):
    tts.engine.remaining_value = 0
    it = await say(tts, "ciao")
    assert "limite giornaliero" in it.last and it.sent[0][1]["ephemeral"] is True and tts.engine.texts == []
    tts.engine.remaining_value = 100                             # con margine il comando funziona
    assert "limite" not in (await say(tts, "ciao")).sent[0][0]


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


async def test_unloading_the_cog_closes_the_engine(tts):
    await tts.cog.cog_unload()
    assert tts.engine.closed


def test_command_has_a_per_user_cooldown_and_a_single_option():
    command = PollyTTS(SimpleNamespace(), PollyConfig()).tts
    assert len(command.checks) == 1                                # il cooldown: l'errore lo gestisce main.py
    params = {p.name: p for p in command.parameters}
    assert list(params) == ["testo"] and params["testo"].required and params["testo"].max_value == pt.MAX_CHARS


# ======================================================== motore: boto3 vero + Polly finto

@pytest.fixture(autouse=True)
def aws_env(monkeypatch, tmp_path):
    """Credenziali di prova e nessun accesso ai file/metadati AWS reali."""
    for var in ("AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_REGION", "AWS_REGION", "POLLY_ENGINE", "TTS_DAILY_CHARS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "nessun-file"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "nessun-file"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


@pytest.fixture
async def polly():
    pytest.importorskip("boto3")
    fake = FakePolly()
    server = TestServer(fake.app())
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    engines = []

    def make(**overrides):
        options = dict(endpoint_url=fake.url, region="eu-central-1", timeout=3, max_attempts=1, daily_chars=0)
        engine = PollyEngine(PollyConfig(**{**options, **overrides}))
        engines.append(engine)
        return engine

    fake.make = make
    yield fake
    for engine in engines:
        await engine.close()
    await server.close()


async def test_request_follows_the_polly_contract_and_is_signed(polly):
    audio = await polly.make().synthesize("ciao a tutti")
    assert audio == polly.audio

    request = polly.requests[0]
    assert request["body"] == {
        "Text": "ciao a tutti", "TextType": "text", "OutputFormat": "mp3",
        "VoiceId": "Giorgio", "LanguageCode": "it-IT", "Engine": "standard",
    }
    auth = request["headers"]["authorization"]
    assert auth.startswith(f"AWS4-HMAC-SHA256 Credential={ACCESS_KEY}/") and "/eu-central-1/polly/aws4_request" in auth
    # la chiave segreta non viaggia mai: solo la firma
    assert all(SECRET_KEY not in str(v) for v in request["headers"].values()) and SECRET_KEY not in str(request["body"])


async def test_engine_and_region_come_from_the_config(polly):
    await polly.make(engine="neural", region="eu-west-1").synthesize("ciao")
    request = polly.requests[0]
    assert request["body"]["Engine"] == "neural" and "/eu-west-1/polly/" in request["headers"]["authorization"]


async def test_user_text_is_sent_as_plain_text_never_as_ssml(polly):
    hostile = "<speak>ciao<break time=\"10s\"/></speak> & \"virgolette\" 'apici' <voice name=\"x\">"
    await polly.make().synthesize(hostile)
    body = polly.requests[0]["body"]
    assert body["Text"] == hostile and body["TextType"] == "text"        # Polly lo legge come testo: nessun markup


async def test_repeated_phrases_come_from_the_cache_for_free(polly):
    engine = polly.make(daily_chars=1000)
    first = await engine.synthesize("ciao")
    assert await engine.synthesize("ciao") == first
    assert len(polly.requests) == 1 and engine.remaining() == 996      # la seconda volta non costa né caratteri né rete
    await engine.synthesize("altro")
    assert len(polly.requests) == 2


async def test_cache_is_bounded(polly, monkeypatch):
    monkeypatch.setattr(pt, "CACHE_MAX_ITEMS", 2)
    engine = polly.make()
    for text in ("uno", "due", "tre"):
        await engine.synthesize(text)
    assert list(engine._cache) == ["due", "tre"]                        # il più vecchio è stato eliminato
    await engine.synthesize("due")                                       # ancora in cache
    assert len(polly.requests) == 3

    monkeypatch.setattr(pt, "CACHE_MAX_ITEMS", 64)
    monkeypatch.setattr(pt, "CACHE_MAX_BYTES", 8000)
    big = polly.make()
    polly.audio = b"x" * 3000                                           # > un quarto del limite: non si tiene
    await big.synthesize("grande")
    assert "grande" not in big._cache and big._cache_bytes == 0


async def test_daily_character_budget(polly):
    engine = polly.make(daily_chars=10)
    assert engine.remaining() == 10
    await engine.synthesize("ciao ciao")                                 # 9 caratteri
    assert engine.remaining() == 1
    with pytest.raises(SpeechError, match="limite giornaliero"):
        await engine.synthesize("troppo lungo")
    assert len(polly.requests) == 1                                      # il rifiuto non chiama (né paga) Polly
    assert await engine.synthesize("ciao ciao") == polly.audio          # ma ciò che è in cache si può sempre ripetere

    engine._day = "2000-01-01"                                           # nuovo giorno (UTC): il contatore riparte
    assert engine.remaining() == 10

    assert polly.make(daily_chars=0).remaining() is None                 # 0 = nessun tetto


@pytest.mark.parametrize("status, code, expected", [
    (403, "UnrecognizedClientException", "credenziali AWS non sono valide"),
    (403, "AccessDeniedException", "polly:SynthesizeSpeech"),
    (400, "ExpiredTokenException", "credenziali AWS non sono valide"),
    (400, "ThrottlingException", "troppe richieste"),
    (400, "EngineNotSupportedException", "POLLY_ENGINE"),
    (400, "LanguageNotSupportedException", "AWS_REGION"),
    (400, "TextLengthExceededException", "troppo lungo"),
    (500, "ServiceFailureException", "non disponibile"),
    (503, "ServiceUnavailable", "non disponibile"),
    (400, "UnCodiceNuovoDiAws", "rifiutato"),
])
async def test_polly_errors_are_mapped_without_leaking_details(polly, caplog, status, code, expected):
    polly.error = (status, code, "dettagli interni arn:aws:iam::123456789012:user/segreto")
    with caplog.at_level("DEBUG"):
        with pytest.raises(SpeechError) as error:
            await polly.make().synthesize("ciao")
    message = str(error.value)
    assert expected in message
    assert "arn:aws" not in message and "123456789012" not in message and SECRET_KEY not in message
    # Nei log del bot compare solo il codice dell'errore. (A livello DEBUG è botocore stesso a stampare il corpo
    # della risposta, ma il bot logga a INFO: qui si controlla ciò che scrive il NOSTRO codice.)
    ours = " ".join(r.getMessage() for r in caplog.records if r.name == "cogs.polly_tts")
    assert code in ours and "arn:aws" not in ours and "123456789012" not in ours and SECRET_KEY not in ours


async def test_slow_unreachable_and_empty_responses(polly):
    polly.delay = 1.0
    with pytest.raises(SpeechError, match="in tempo"):
        await polly.make(timeout=0.3).synthesize("ciao")

    with pytest.raises(SpeechError, match="non è raggiungibile"):
        await PollyEngine(PollyConfig(endpoint_url="http://127.0.0.1:1", max_attempts=1, timeout=2)).synthesize("ciao")

    polly.delay, polly.empty = 0, True
    with pytest.raises(SpeechError, match="nessun audio"):
        await polly.make().synthesize("ciao")


async def test_failed_synthesis_is_not_cached_or_charged(polly):
    engine = polly.make(daily_chars=100)
    polly.error = (500, "ServiceFailureException", "x")
    with pytest.raises(SpeechError):
        await engine.synthesize("ciao")
    assert engine.remaining() == 100 and "ciao" not in engine._cache
    polly.error = None
    assert await engine.synthesize("ciao") == polly.audio                # al secondo tentativo funziona


async def test_missing_credentials_are_explained(polly, monkeypatch):
    engine = polly.make()
    assert await engine.problem() is None                                # con le credenziali nel .env va tutto bene

    monkeypatch.delenv("AWS_ACCESS_KEY_ID")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY")
    no_creds = polly.make()
    assert "AWS_ACCESS_KEY_ID" in await no_creds.problem()
    with pytest.raises(SpeechError, match="credenziali"):
        await no_creds.synthesize("ciao")
    assert polly.requests == []                                          # senza credenziali non parte nessuna richiesta


async def test_credential_check_is_cached_including_failures(polly, monkeypatch):
    """Il controllo può essere lento (file, metadati EC2): /tts deve rispondere entro 3 secondi."""
    engine = polly.make()
    calls = []
    monkeypatch.setattr(engine, "_problem_sync", lambda: calls.append(1) or "manca qualcosa")
    assert await engine.problem() == "manca qualcosa" and await engine.problem() == "manca qualcosa"
    assert len(calls) == 1
    monkeypatch.setattr(pt, "CONFIG_CHECK_TTL", -1)                     # scaduto: si ricontrolla
    await engine.problem()
    assert len(calls) == 2


async def test_without_boto3_the_bot_still_starts_and_explains(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)                      # import boto3 -> ImportError
    engine = PollyEngine(PollyConfig())
    assert "pip install boto3" in await engine.problem()
    with pytest.raises(SpeechError, match="pip install boto3"):
        await engine.synthesize("ciao")


async def test_closing_the_engine_is_safe_and_repeatable(polly):
    engine = polly.make()
    await engine.synthesize("ciao")
    await engine.close()
    await engine.close()
    assert await engine.synthesize("altro")                              # si riapre da solo


def test_config_from_env(monkeypatch):
    default = PollyConfig.from_env()
    assert (default.region, default.engine, default.daily_chars) == ("eu-central-1", "standard", 50000)

    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert PollyConfig.from_env().region == "eu-west-1"
    monkeypatch.setenv("AWS_REGION", "eu-south-2")                       # AWS_REGION ha la precedenza
    monkeypatch.setenv("POLLY_ENGINE", " Neural ")
    monkeypatch.setenv("TTS_DAILY_CHARS", "1234")
    config = PollyConfig.from_env()
    assert (config.region, config.engine, config.daily_chars) == ("eu-south-2", "neural", 1234)

    monkeypatch.setenv("POLLY_ENGINE", "magico")                         # non valido: si torna al predefinito
    monkeypatch.setenv("TTS_DAILY_CHARS", "tanti")
    config = PollyConfig.from_env()
    assert (config.engine, config.daily_chars) == ("standard", 50000)
    monkeypatch.setenv("TTS_DAILY_CHARS", "-5")
    assert PollyConfig.from_env().daily_chars == 0                       # negativo = nessun tetto


# ============================================================ catena completa con audio vero

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg non installato")
async def test_the_audio_from_polly_is_playable_by_discord_ffmpeg(polly, tmp_path):
    """Dalla risposta di Polly al file temporaneo letto da FFmpegPCMAudio, esattamente come fa il bot."""
    mp3 = tmp_path / "prova.mp3"
    made = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-codec:a", "libmp3lame", str(mp3)], capture_output=True,
    )
    if made.returncode != 0 or not mp3.exists():
        pytest.skip("ffmpeg senza libmp3lame")
    polly.audio = mp3.read_bytes()

    audio = await polly.make().synthesize("prova di riproduzione")
    path = tmp_path / "tts.mp3"
    path.write_bytes(audio)
    source = discord.FFmpegPCMAudio(str(path))
    try:
        frames = []
        while True:
            frame = source.read()                                         # 20ms di PCM a 48kHz stereo
            if not frame:
                break
            frames.append(frame)
    finally:
        source.cleanup()
    assert len(frames) > 20 and all(len(f) == 3840 for f in frames[:-1]) and any(any(f) for f in frames)
