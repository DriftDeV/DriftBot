"""Test del cog Music con voice client / interazioni finti (nessuna rete, nessun FFmpeg)."""

import asyncio
from types import SimpleNamespace

import discord
import pytest

from cogs import music
from cogs.music import Music, NoMatches, Track, extract_track, is_url


# ----------------------------------------------------------------- finti

class FakeSource(discord.AudioSource):
    def __init__(self, url, **kwargs):
        self.url = url

    def read(self):
        return b""


class FakeVC:
    def __init__(self, channel):
        self.channel = channel
        self.playing = False
        self.paused = False
        self.connected = True
        self.after = None

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing and not self.paused

    def is_paused(self):
        return self.paused

    def play(self, source, after=None):
        self.playing, self.paused, self.after = True, False, after

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        was_playing = self.playing
        self.playing = self.paused = False
        if was_playing and self.after:
            self.after(None)  # discord.py chiama `after` anche su stop()

    async def disconnect(self):
        self.connected = False

    async def move_to(self, channel):
        self.channel = channel


class FakeGuild:
    id = 1

    def __init__(self):
        self.voice_client = None


class FakeInteraction:
    def __init__(self, guild, channel, user_id=42):
        self.guild = guild
        self.user = SimpleNamespace(id=user_id, voice=SimpleNamespace(channel=channel) if channel else None)
        self.sent = []
        self.response = SimpleNamespace(
            send_message=self._send, defer=self._defer, is_done=lambda: False
        )
        self.followup = SimpleNamespace(send=self._send)

    async def _send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def _defer(self, **kwargs):
        pass

    @property
    def last(self):
        return self.sent[-1][0]


def make_track(n):
    return Track(title=f"t{n}", author=f"a{n}", webpage_url=f"https://x/{n}", stream_url=f"https://s/{n}")


@pytest.fixture
async def env(monkeypatch):
    loop = asyncio.get_running_loop()
    bot = SimpleNamespace(loop=loop, user=SimpleNamespace(id=999))
    cog = Music(bot)
    voice_channel = SimpleNamespace(name="vc")
    guild = FakeGuild()

    async def connect():
        guild.voice_client = FakeVC(voice_channel)
        return guild.voice_client

    voice_channel.connect = connect

    tracks = iter(range(1, 100))
    monkeypatch.setattr(music, "extract_track", lambda q: make_track(next(tracks)))
    monkeypatch.setattr(music.discord, "FFmpegPCMAudio", FakeSource)
    return SimpleNamespace(cog=cog, guild=guild, channel=voice_channel)


async def settle():
    """Lascia girare i task creati da run_coroutine_threadsafe."""
    for _ in range(5):
        await asyncio.sleep(0)


async def play(env, q="song"):
    it = FakeInteraction(env.guild, env.channel)
    await env.cog.play.callback(env.cog, it, q)
    return it


# ----------------------------------------------------------------- funzioni pure

def test_is_url():
    assert is_url("https://youtu.be/abc")
    assert is_url("http://example.com/x.mp3")
    assert not is_url("never gonna give you up")
    assert not is_url("file:///etc/passwd")
    assert not is_url("ftp://example.com/x")


def test_extract_track_search_and_playlist(monkeypatch):
    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, target, download=False):
            seen["target"] = target
            return {"entries": [{"title": "T", "uploader": "U", "url": "https://s", "webpage_url": "https://w"}]}

    monkeypatch.setattr(music.yt_dlp, "YoutubeDL", FakeYDL)
    track = extract_track("some song")
    assert seen["target"] == "ytsearch1:some song"
    assert (track.title, track.author, track.stream_url, track.webpage_url) == ("T", "U", "https://s", "https://w")

    extract_track("https://youtu.be/x")
    assert seen["target"] == "https://youtu.be/x"


def test_extract_track_no_matches(monkeypatch):
    class EmptyYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, target, download=False):
            return {"entries": []}

    monkeypatch.setattr(music.yt_dlp, "YoutubeDL", EmptyYDL)
    with pytest.raises(NoMatches):
        extract_track("nothing")


def test_track_staleness():
    track = make_track(1)
    assert not track.is_stale()
    track.resolved_at -= music.STREAM_URL_TTL + 1
    assert track.is_stale()


# ----------------------------------------------------------------- comandi

async def test_play_requires_voice(env):
    it = FakeInteraction(env.guild, None)
    await env.cog.play.callback(env.cog, it, "x")
    assert "canale vocale" in it.last
    assert env.guild.voice_client is None


async def test_play_starts_then_queues(env):
    first = await play(env)
    assert "Track caricata" in first.last and "t1" in first.last
    vc = env.guild.voice_client
    assert vc.playing and env.cog.players[1].current.title == "t1"

    second = await play(env)
    assert "coda" in second.last and "posizione 1" in second.last
    assert [t.title for t in env.cog.players[1].queue] == ["t2"]


async def test_track_end_advances_then_idles(env):
    await play(env)
    await play(env)
    vc, player = env.guild.voice_client, env.cog.players[1]

    vc.stop()  # fine naturale della traccia 1 -> parte la 2
    await settle()
    assert player.current.title == "t2" and vc.playing

    vc.stop()  # fine della 2, coda vuota
    await settle()
    assert player.current is None
    assert player.idle_task is not None
    env.cog._cancel_idle(player)


async def test_skip(env):
    await play(env)
    it = FakeInteraction(env.guild, env.channel)
    assert await env.cog.skip_if_active(it) is True
    assert "Non ci sono altre canzoni" in it.last  # coda vuota: la traccia corrente continua
    assert env.guild.voice_client.playing

    await play(env)
    it = FakeInteraction(env.guild, env.channel)
    assert await env.cog.skip_if_active(it) is True
    assert "t2" in it.last
    await settle()
    assert env.cog.players[1].current.title == "t2"


async def test_skip_not_handled_without_music(env):
    it = FakeInteraction(env.guild, env.channel)
    assert await env.cog.skip_if_active(it) is False
    assert it.sent == []  # l'interazione resta libera per l'AI cover


async def test_skip_wrong_channel(env):
    await play(env)
    other = FakeInteraction(env.guild, SimpleNamespace(name="other"))
    assert await env.cog.skip_if_active(other) is True
    assert "stesso canale" in other.last


async def test_pause_resume(env):
    await play(env)
    vc = env.guild.voice_client

    it = FakeInteraction(env.guild, env.channel)
    await env.cog.pause.callback(env.cog, it)
    assert vc.paused and "pausa" in it.last

    it = FakeInteraction(env.guild, env.channel)
    await env.cog.resume.callback(env.cog, it)
    assert not vc.paused and "riproduzione" in it.last

    it = FakeInteraction(env.guild, env.channel)
    await env.cog.resume.callback(env.cog, it)
    assert "non è in pausa" in it.last


async def test_setvolume_applies_live(env):
    await play(env)
    it = FakeInteraction(env.guild, env.channel)
    await env.cog.setvolume.callback(env.cog, it, 40)
    player = env.cog.players[1]
    assert player.volume == 40 and player.source.volume == pytest.approx(0.4)
    assert "40" in it.last


async def test_volume_carries_to_next_track(env):
    await play(env)
    await play(env)
    await env.cog.setvolume.callback(env.cog, FakeInteraction(env.guild, env.channel), 25)
    env.guild.voice_client.stop()
    await settle()
    assert env.cog.players[1].source.volume == pytest.approx(0.25)


async def test_stop_clears_everything(env):
    await play(env)
    await play(env)
    vc = env.guild.voice_client
    it = FakeInteraction(env.guild, env.channel)
    await env.cog.stop.callback(env.cog, it)
    await settle()
    assert "stoppata" in it.last
    assert 1 not in env.cog.players
    assert not vc.connected and not vc.playing


async def test_controls_without_music(env):
    for cmd in (env.cog.pause, env.cog.resume, env.cog.stop):
        it = FakeInteraction(env.guild, env.channel)
        await cmd.callback(env.cog, it)
        assert "Non sto riproducendo" in it.last


async def test_play_refuses_when_other_audio_is_playing(env):
    vc = await env.channel.connect()
    vc.playing = True  # es. TTS / soundboard
    it = await play(env)
    assert "altro audio" in it.last
    assert not env.cog.players[1].queue


async def test_play_no_matches(env, monkeypatch):
    def boom(q):
        raise NoMatches(q)

    monkeypatch.setattr(music, "extract_track", boom)
    it = await play(env, "zzz")
    assert "Nessun risultato" in it.last
    assert env.guild.voice_client is None


async def test_unplayable_track_is_skipped(env, monkeypatch):
    await play(env)
    await play(env)
    await play(env)  # coda: t2, t3

    calls = {"n": 0}
    real_play = env.guild.voice_client.play

    def flaky_play(source, after=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ffmpeg non trovato")
        real_play(source, after=after)

    env.guild.voice_client.play = flaky_play
    env.guild.voice_client.stop()
    await settle()
    assert env.cog.players[1].current.title == "t3"  # t2 saltata


async def test_bot_disconnect_cleans_state(env):
    await play(env)
    bot_member = SimpleNamespace(id=999, guild=env.guild)
    await env.cog.on_voice_state_update(
        bot_member, SimpleNamespace(channel=env.channel), SimpleNamespace(channel=None)
    )
    assert 1 not in env.cog.players
