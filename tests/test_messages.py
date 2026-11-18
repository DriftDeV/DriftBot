"""Messaggi, embed e testi visibili agli utenti: limiti di Discord, coerenza e comportamento."""

from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

from cogs import ace_step_cog, ai_cover_cog, escape_md
from cogs import music as music_cog
from cogs.ace_step_cog import AceStepMusic
from fakes import FakeGuild, FakeInteraction, FakeVC, make_channel
from pathlib import Path

COGS_DIR = Path(__file__).resolve().parent.parent / "src" / "cogs"


# --------------------------------------------------------- testi dei comandi slash

async def load_all_commands():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    for path in sorted(COGS_DIR.glob("*.py")):
        if not path.name.startswith("_"):
            await bot.load_extension(f"cogs.{path.stem}")
    return bot, [command.to_dict(bot.tree) for command in bot.tree.get_commands()]


async def test_command_texts_respect_discord_limits_and_have_no_placeholders():
    """Discord rifiuta la sincronizzazione di descrizioni vuote o troppo lunghe; "…" è il segnaposto di default."""
    bot, commands_ = await load_all_commands()
    assert 0 < len(commands_) <= 100
    for command in commands_:
        label = f"/{command['name']}"
        assert 1 <= len(command["description"]) <= 100 and command["description"] != "…", label
        assert command["name"] == command["name"].lower() and len(command["name"]) <= 32, label
        for option in command.get("options", []):
            where = f"{label} {option['name']}"
            assert 1 <= len(option["description"]) <= 100 and option["description"] != "…", where
            assert option["name"] == option["name"].lower() and len(option["name"]) <= 32, where
            for choice in option.get("choices", []):
                assert 1 <= len(str(choice["name"])) <= 100 and len(str(choice["value"])) <= 100, where
    await bot.close()


async def test_command_texts_are_in_italian_and_without_known_typos():
    bot, commands_ = await load_all_commands()
    texts = []
    for command in commands_:
        texts.append(command["description"])
        texts.extend(option["description"] for option in command.get("options", []))
    joined = " | ".join(texts)
    for typo in ("souno", "Linuga"):
        assert typo not in joined
    for english in ("Generate speech", "Disconnect the bot", "Rename a Speaker", "What should I say", "Which voice"):
        assert english not in joined
    await bot.close()


# -------------------------------------------------------------------- escape e formato

def test_escape_md_neutralizes_discord_markdown():
    assert escape_md("**grassetto** _corsivo_ `codice` ~~barrato~~ ||spoiler|| > citazione") == (
        "\\*\\*grassetto\\*\\* \\_corsivo\\_ \\`codice\\` \\~\\~barrato\\~\\~ \\|\\|spoiler\\|\\| \\> citazione"
    )
    assert escape_md("testo normale con [verse] e punteggiatura, ok!") == "testo normale con [verse] e punteggiatura, ok!"
    assert escape_md("a\\b") == "a\\\\b"


def test_music_titles_are_escaped_trimmed_and_flattened():
    fmt = music_cog.fmt
    assert fmt("**Hit** _2026_") == "\\*\\*Hit\\*\\* \\_2026\\_"
    assert fmt("riga uno\nriga   due\t!") == "riga uno riga due !"                  # niente a-capo nei messaggi
    long_title = "x" * 500
    assert len(fmt(long_title)) <= 100 and fmt(long_title).endswith("…")


async def test_play_message_does_not_let_a_video_title_break_the_formatting(monkeypatch):
    guild = FakeGuild(1)
    channel = make_channel(guild)
    hostile = music_cog.Track(title="**FREE** @everyone _x_ " + "y" * 300, author="`a`", webpage_url="https://x", stream_url="https://s")
    monkeypatch.setattr(music_cog, "extract_track", lambda q: hostile)
    monkeypatch.setattr(music_cog.discord, "FFmpegPCMAudio", lambda url, **kw: discord.PCMAudio.__new__(discord.PCMAudio))
    cog = music_cog.Music(SimpleNamespace(loop=__import__("asyncio").get_running_loop(), user=SimpleNamespace(id=999)))
    it = FakeInteraction(guild, channel)
    monkeypatch.setattr(music_cog.discord, "PCMVolumeTransformer", lambda source, volume=1.0: SimpleNamespace(volume=volume))
    await cog.play.callback(cog, it, "qualcosa")
    message = it.last
    assert "Traccia caricata" in message and "\\*\\*FREE\\*\\*" in message and "\\`a\\`" in message
    assert len(message) < 300                                                         # titolo troncato


# ---------------------------------------------------------------- /skip dell'AI cover

@pytest.fixture
def cover():
    guild = FakeGuild(7)
    channel = make_channel(guild)
    cog = ai_cover_cog.AICover(SimpleNamespace(get_cog=lambda name: None))
    vc = FakeVC(channel)
    vc.playing = True
    guild.voice_client = vc
    return SimpleNamespace(cog=cog, guild=guild, channel=channel, vc=vc)


async def test_skip_does_not_promise_a_next_song_when_the_queue_is_empty(cover):
    it = FakeInteraction(cover.guild, cover.channel)
    await cover.cog.skip.callback(cover.cog, it)
    embed = it.last
    assert embed.title == "⏭️ Canzone saltata!" and "Non ci sono altre richieste" in embed.description
    assert not cover.vc.playing                                          # la canzone è stata davvero fermata


async def test_skip_with_more_requests_waiting_announces_the_next_one(cover):
    cover.cog.queue.put_nowait({"interaction": None})
    it = FakeInteraction(cover.guild, cover.channel)
    await cover.cog.skip.callback(cover.cog, it)
    assert "Passo alla prossima" in it.last.title and it.last.description is None


async def test_skip_errors_are_private(cover):
    cover.vc.playing = False
    it = FakeInteraction(cover.guild, cover.channel)
    await cover.cog.skip.callback(cover.cog, it)
    assert "nessuna canzone" in it.last and it.sent[-1][1]["ephemeral"] is True

    cover.vc.playing = True
    outsider = FakeInteraction(cover.guild, make_channel(cover.guild, "altro"))
    await cover.cog.skip.callback(cover.cog, outsider)
    assert "stesso canale" in outsider.last and outsider.sent[-1][1]["ephemeral"] is True
    assert cover.vc.playing


async def test_ai_cover_notification_in_the_channel_mentions_the_requester(cover):
    """Con il token scaduto un embed da solo finirebbe nel canale senza avvisare nessuno."""
    it = FakeInteraction(cover.guild, cover.channel)
    it.followup_error = discord.HTTPException(SimpleNamespace(status=401, reason="x"), "Invalid Webhook Token")
    await cover.cog._notify(it, embed=discord.Embed(title="🎶 Riproduzione in Corso!"))
    content, kwargs = it.channel.sent[-1]
    assert content == it.user.mention and kwargs["embed"].title == "🎶 Riproduzione in Corso!"

    await cover.cog._notify(it, content="❌ errore già con menzione")       # un testo esistente non viene toccato
    assert it.channel.sent[-1][0] == "❌ errore già con menzione"


# ------------------------------------------------------ dimensione degli embed di /ace-step

def result_embed(prompt, lyrics, note, label="Claude claude-opus-5-5"):
    interaction = FakeInteraction(FakeGuild(1), None)
    return AceStepMusic._result_embed(
        interaction, prompt, 180, lyrics, "ai", label, note,
        {"metas": {"bpm": 120, "keyscale": "C major"}}, 123.0,
    )


def test_worst_case_result_embed_fits_discord_limits():
    # testo di 2000 caratteri tutti da escapare (diventano 4000), prompt e nota al massimo
    embed = result_embed("p" * 500, "*" * 2000, "n" * 1024)
    assert len(embed) <= 6000                                  # limite di Discord
    assert len(embed.description) <= 4096 and all(len(f.value) <= 1024 for f in embed.fields)
    assert len(embed.fields) <= 25 and len(embed.title) <= 256 and len(embed.footer.text) <= 2048


def test_oversized_embed_is_shortened_instead_of_failing(monkeypatch):
    monkeypatch.setattr(ace_step_cog, "EMBED_SAFE_LIMIT", 600)
    embed = result_embed("prompt", "[verse]\n" + "una riga di testo\n" * 200, None)
    assert len(embed) <= 600 and embed.description.endswith("…")
    assert embed.fields[0].value == "prompt"                    # si accorcia il testo, non il resto


def test_result_embed_escapes_the_lyrics():
    embed = result_embed("p", "[verse]\nuna *riga* con_underscore", None)
    assert "\\*riga\\*" in embed.description and "con\\_underscore" in embed.description
