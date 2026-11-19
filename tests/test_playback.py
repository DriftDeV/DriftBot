"""Controlli globali /skip /pause /resume /stop /setvolume: valgono per qualunque audio nella vocale."""

import asyncio
from types import SimpleNamespace

import discord
import pytest

from cogs import ai_cover_cog
from cogs.playback import Playback, volume_of, with_volume
from fakes import FakeGuild, FakeInteraction, FakeSource, FakeVC, make_channel


class FakeMusic:
    def __init__(self, upcoming=None):
        self._upcoming, self.cleared = upcoming, []

    def upcoming(self, guild):
        return self._upcoming

    def clear(self, guild_id):
        self.cleared.append(guild_id)


class FakeCover:
    def __init__(self, waiting=False):
        self.queue = asyncio.Queue()
        if waiting:
            self.queue.put_nowait({})
        self.cleared = []

    def clear_queue(self, guild_id):
        self.cleared.append(guild_id)


@pytest.fixture
def env():
    guild = FakeGuild(7)
    channel = make_channel(guild)
    vc = FakeVC(channel)
    vc.play(discord.PCMVolumeTransformer(FakeSource("qualsiasi cog")))   # ACE-Step, cover o musica: non importa
    guild.voice_client = vc
    cogs = {}
    bot = SimpleNamespace(get_cog=lambda name: cogs.get(name))
    cog = Playback(bot)
    cogs["Playback"] = cog
    return SimpleNamespace(cog=cog, cogs=cogs, guild=guild, channel=channel, vc=vc, bot=bot)


def ask(env, channel="same"):
    return FakeInteraction(env.guild, env.channel if channel == "same" else channel)


# ------------------------------------------------------------------------- /skip

async def test_skip_stops_whatever_is_playing(env):
    it = ask(env)
    await env.cog.skip.callback(env.cog, it)
    assert not env.vc.playing and "Saltata" in it.last and "Non c'è altro" in it.last


async def test_skip_announces_the_next_music_track(env):
    env.cogs["Music"] = FakeMusic("**t2** di **a2**")
    it = ask(env)
    await env.cog.skip.callback(env.cog, it)
    assert "**t2** di **a2**" in it.last


async def test_skip_announces_waiting_cover_requests(env):
    env.cogs["AICover"] = FakeCover(waiting=True)
    it = ask(env)
    await env.cog.skip.callback(env.cog, it)
    assert "prossima richiesta" in it.last


@pytest.mark.parametrize("command", ["skip", "pause", "resume", "stop"])
async def test_controls_with_nothing_playing_are_private(env, command):
    env.vc.playing = False
    it = ask(env)
    await getattr(env.cog, command).callback(env.cog, it)
    assert "Non sto riproducendo" in it.last and it.sent[-1][1]["ephemeral"] is True


@pytest.mark.parametrize("command", ["skip", "pause", "stop"])
async def test_controls_from_another_channel_are_refused(env, command):
    it = ask(env, make_channel(env.guild, "altro"))
    await getattr(env.cog, command).callback(env.cog, it)
    assert "stesso canale" in it.last and it.sent[-1][1]["ephemeral"] is True
    assert env.vc.playing and env.vc.connected


# ------------------------------------------------------------------ pause/resume

async def test_pause_and_resume(env):
    it = ask(env)
    await env.cog.pause.callback(env.cog, it)
    assert env.vc.paused and "pausa" in it.last

    it = ask(env)
    await env.cog.pause.callback(env.cog, it)
    assert "già in pausa" in it.last

    it = ask(env)
    await env.cog.resume.callback(env.cog, it)
    assert not env.vc.paused and "Riprendo" in it.last

    it = ask(env)
    await env.cog.resume.callback(env.cog, it)
    assert "Non è in pausa" in it.last


async def test_skip_and_stop_also_work_while_paused(env):
    env.vc.paused = True
    it = ask(env)
    await env.cog.skip.callback(env.cog, it)
    assert not env.vc.playing and "Saltata" in it.last


# -------------------------------------------------------------------------- /stop

async def test_stop_clears_every_queue_and_leaves(env):
    music, cover = FakeMusic(), FakeCover()
    env.cogs.update(Music=music, AICover=cover)
    it = ask(env)
    await env.cog.stop.callback(env.cog, it)
    assert music.cleared == [7] and cover.cleared == [7]
    assert not env.vc.playing and not env.vc.connected and "Fermato" in it.last


# ---------------------------------------------------------------------- /setvolume

async def test_setvolume_applies_live_and_to_next_sources(env):
    it = ask(env)
    await env.cog.setvolume.callback(env.cog, it, 40)
    assert env.vc.source.volume == pytest.approx(0.4) and "40" in it.last
    assert volume_of(env.bot, 7) == 40
    assert with_volume(env.bot, 7, FakeSource("x")).volume == pytest.approx(0.4)   # cover / ACE-Step / musica successive
    assert with_volume(env.bot, 8, FakeSource("x")).volume == pytest.approx(1.0)   # un altro server non cambia


async def test_setvolume_without_audio_is_stored_for_later(env):
    env.vc.playing = False
    await env.cog.setvolume.callback(env.cog, ask(env), 15)
    assert volume_of(env.bot, 7) == 15


async def test_setvolume_from_another_channel_is_refused_while_playing(env):
    it = ask(env, make_channel(env.guild, "altro"))
    await env.cog.setvolume.callback(env.cog, it, 5)
    assert "stesso canale" in it.last and volume_of(env.bot, 7) == 100


def test_volume_defaults_without_the_playback_cog():
    assert volume_of(SimpleNamespace(), 1) == 100


# ------------------------------------------------------------ coda dell'AI cover

async def test_cover_clear_queue_drops_only_that_guild_and_keeps_counters_right():
    cog = ai_cover_cog.AICover(SimpleNamespace())
    mine = {"interaction": SimpleNamespace(guild_id=7)}
    other = {"interaction": SimpleNamespace(guild_id=8)}
    for item in (mine, other, mine):
        cog.queue.put_nowait(item)
    cog.clear_queue(7)
    assert cog.queue.qsize() == 1 and cog.queue.get_nowait() is other
    cog.queue.task_done()
    await asyncio.wait_for(cog.queue.join(), 1)          # nessun task_done in sospeso
