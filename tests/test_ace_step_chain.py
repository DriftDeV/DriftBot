"""
La catena completa su GPU da 8 GB:  prompt -> LLM scrive il testo -> LLM scaricato -> ACE-Step compone.
Il punto critico è l'ORDINE: ACE-Step non deve partire finché l'LLM è in VRAM.
"""

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestServer

from cogs import ace_step_cog as ace
from cogs.ace_step_cog import AceStepConfig, AceStepMusic
from fake_servers import FakeAceStep, FakeOllama
from fakes import FakeGuild, FakeInteraction, make_channel
from lyrics_llm import LyricsConfig


@pytest.fixture
async def chain():
    events = []
    acestep, ollama = FakeAceStep(events), FakeOllama(events)
    servers = [TestServer(acestep.app()), TestServer(ollama.app())]
    for server in servers:
        await server.start_server()
    acestep.url = str(servers[0].make_url("")).rstrip("/")
    ollama.url = str(servers[1].make_url("")).rstrip("/")

    llm = LyricsConfig(base_url=ollama.url, timeout=2, unload_timeout=0.5, poll_interval=0.01)
    config = AceStepConfig(base_url=acestep.url, poll_interval=0.01, timeout=5, max_seconds=180, llm=llm)
    cog = AceStepMusic(SimpleNamespace(), config)
    guild = FakeGuild(7)
    guild.filesize_limit = 10_000_000
    channel = make_channel(guild)
    yield SimpleNamespace(cog=cog, ace=acestep, llm=ollama, events=events, guild=guild,
                          channel=channel, config=config)
    await cog.cog_unload()
    for server in servers:
        await server.close()


async def run(chain, prompt="ballata malinconica sul mare", durata=None, testo=None,
              lingua=None, strumentale=False, user_id=42):
    it = FakeInteraction(chain.guild, chain.channel, user_id=user_id)
    await chain.cog.ace_step.callback(chain.cog, it, prompt, durata, testo, lingua, strumentale)
    return it


def final(it):
    return it.edits[-1]


def embed_fields(it):
    return {f.name: f.value for f in final(it)["embed"].fields}


# ------------------------------------------------------------------- la catena

async def test_lyrics_are_written_by_the_llm_and_used_by_acestep(chain):
    chain.ace.running_polls = 1                     # il brano non è pronto al primo controllo
    it = await run(chain)
    body = chain.ace.submitted[0]
    assert body["lyrics"].startswith("[verse]") and "Luci di città" in body["lyrics"]
    assert body["vocal_language"] == "it"

    embed = final(it)["embed"]
    assert "Luci di città" in embed.description                        # il testo è mostrato all'utente
    assert "testo scritto dall'AI" in embed_fields(it)["Dettagli"]
    assert "⚠️ Nota" not in embed_fields(it)
    assert final(it)["attachments"][0].fp.read()                        # e il brano è allegato

    user_message = chain.llm.chat_requests[0]["messages"][1]["content"]
    assert "ballata malinconica sul mare" in user_message and "180 seconds" in user_message
    texts = [e.get("content") or "" for e in it.edits]
    assert any("scrivendo il testo" in t for t in texts) and any("componendo" in t for t in texts)


async def test_llm_is_unloaded_before_acestep_starts(chain):
    """Il requisito delle 8 GB: la VRAM dell'LLM è libera PRIMA che ACE-Step parta."""
    chain.llm.linger_polls = 5                      # l'LLM resta in memoria ancora per qualche controllo
    await run(chain)
    ev = chain.events
    last_loaded = max(i for i, e in enumerate(ev) if e == "ps:loaded")
    first_empty_after = next(i for i, e in enumerate(ev) if e == "ps:empty" and i > last_loaded)
    assert ev.index("llm_chat_end") < first_empty_after < ev.index("ace_release")


async def test_explicit_unload_when_the_model_ignores_keep_alive(chain):
    chain.llm.sticky = True                         # ignora keep_alive:0
    await run(chain)
    assert chain.llm.explicit_unloads == 1
    assert chain.events.index("llm_unload_explicit") < chain.events.index("ace_release")


async def test_acestep_still_runs_if_the_llm_cannot_be_unloaded(chain):
    chain.config.llm.unload_timeout = 0.1
    chain.llm.sticky = chain.llm.ignore_explicit = True
    it = await run(chain)
    assert final(it)["embed"].title == "🎵 Musica generata"             # non resta bloccato per sempre


async def test_given_lyrics_or_instrumental_skip_the_llm(chain):
    it = await run(chain, testo="[verse]\nil mio testo\nsecondo verso")
    assert chain.ace.submitted[-1]["lyrics"].startswith("[verse]\nil mio testo")
    assert "con testo" in embed_fields(it)["Dettagli"]

    it = await run(chain, strumentale=True)
    assert chain.ace.submitted[-1]["lyrics"] == "[Instrumental]"
    assert "strumentale" in embed_fields(it)["Dettagli"]
    assert chain.llm.chat_requests == [] and "llm_chat_start" not in chain.events


async def test_lyrics_and_instrumental_together_are_rejected(chain):
    it = await run(chain, testo="un testo", strumentale=True)
    assert "in contrasto" in it.last and it.sent[-1][1]["ephemeral"]
    assert chain.ace.submitted == [] and chain.llm.chat_requests == []


async def test_llm_disabled_means_instrumental(chain):
    chain.config.llm.enabled = False
    it = await run(chain)
    assert chain.ace.submitted[0]["lyrics"] == "[Instrumental]" and chain.llm.chat_requests == []
    assert "⚠️ Nota" not in embed_fields(it)


# ------------------------------------------------------------ durata e lingua

async def test_default_duration_is_the_maximum(chain):
    await run(chain, durata=None)
    assert chain.ace.submitted[-1]["audio_duration"] == 180

    chain.config.max_seconds = 90
    await run(chain, durata=None)
    assert chain.ace.submitted[-1]["audio_duration"] == 90

    await run(chain, durata=60)
    assert chain.ace.submitted[-1]["audio_duration"] == 60
    await run(chain, durata=500)                                       # oltre il massimo: limitato
    assert chain.ace.submitted[-1]["audio_duration"] == 90


async def test_language_reaches_both_the_llm_and_acestep(chain):
    await run(chain, lingua="en")
    assert chain.ace.submitted[-1]["vocal_language"] == "en"
    assert "English" in chain.llm.chat_requests[-1]["messages"][0]["content"]

    chain.config.default_language = "es"
    await run(chain, lingua=None)
    assert chain.ace.submitted[-1]["vocal_language"] == "es"
    await run(chain, lingua="xx")                                      # lingua inventata: usa il default
    assert chain.ace.submitted[-1]["vocal_language"] == "es"


async def test_messy_llm_output_is_cleaned_before_reaching_acestep(chain):
    chain.llm.content = ("<think>ok</think>Certo! Ecco il testo:\n\n## Strofa 1\n**Luci** di città\n"
                         "passo lento\n\n**Ritornello**\ncanto con te\nresta qui")
    await run(chain)
    lyrics = chain.ace.submitted[0]["lyrics"]
    assert lyrics.startswith("[verse]") and "[chorus]" in lyrics
    assert not any(junk in lyrics for junk in ("Certo", "think", "**", "##"))


# ------------------------------------------------- se l'LLM non va, il brano si fa lo stesso

@pytest.mark.parametrize("setup, expected", [
    (lambda c: setattr(c.llm, "chat_status", 404), "ollama pull qwen2.5:7b"),
    (lambda c: setattr(c.llm, "chat_status", 500), "HTTP 500"),
    (lambda c: setattr(c.llm, "content", "boh"), "utilizzabile"),
    (lambda c: (setattr(c.config.llm, "timeout", 0.1), setattr(c.llm, "delay", 0.5)), "in tempo"),
    (lambda c: setattr(c.config.llm, "base_url", "http://127.0.0.1:1"), "non è raggiungibile"),
])
async def test_llm_failure_falls_back_to_an_instrumental_track_with_a_note(chain, setup, expected):
    setup(chain)
    it = await run(chain)
    assert chain.ace.submitted[0]["lyrics"] == "[Instrumental]"
    assert final(it)["embed"].title == "🎵 Musica generata"
    note = embed_fields(it)["⚠️ Nota"]
    assert expected in note and "strumentale" in note.lower()
    assert "strumentale" in embed_fields(it)["Dettagli"]


async def test_llm_is_unloaded_even_when_it_fails(chain):
    chain.llm.chat_status, chain.llm.sticky = 500, True
    await run(chain)
    assert chain.llm.explicit_unloads == 1 and not chain.llm.loaded
    assert chain.events.index("llm_unload_explicit") < chain.events.index("ace_release")


# -------------------------------------------------------- un lavoro GPU alla volta

async def test_one_gpu_job_at_a_time_across_users(chain):
    """L'LLM del secondo utente non può caricarsi mentre ACE-Step lavora per il primo."""
    chain.ace.gate = asyncio.Event()
    first = asyncio.create_task(run(chain, user_id=1))
    second = asyncio.create_task(run(chain, user_id=2))
    while "ace_release" not in chain.events:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.2)
    assert chain.events.count("llm_chat_start") == 1          # il secondo è ancora in attesa

    chain.ace.gate.set()
    for task in (first, second):
        assert final(await task)["embed"].title == "🎵 Musica generata"
    starts = [i for i, e in enumerate(chain.events) if e == "llm_chat_start"]
    assert len(starts) == 2 and starts[1] > chain.events.index("ace_done")


async def test_waiting_user_is_told_about_the_queue(chain):
    chain.ace.gate = asyncio.Event()
    first = asyncio.create_task(run(chain, user_id=1))
    while "ace_release" not in chain.events:
        await asyncio.sleep(0.01)
    second = asyncio.create_task(run(chain, user_id=2))
    await asyncio.sleep(0.2)
    chain.ace.gate.set()
    it_first, it_second = await first, await second
    assert any("In coda" in (e.get("content") or "") for e in it_second.edits)
    assert not any("In coda: " in (e.get("content") or "") for e in it_first.edits)


def test_default_language_from_env(monkeypatch):
    monkeypatch.setenv("ACESTEP_DEFAULT_LANGUAGE", "FR")
    assert AceStepConfig.from_env().default_language == "fr"
    monkeypatch.setenv("ACESTEP_DEFAULT_LANGUAGE", "klingon")
    assert AceStepConfig.from_env().default_language == "it"
    assert ace.LANGUAGES.keys() == {"it", "en", "es", "fr", "de", "pt"}


async def test_lyrics_are_escaped_in_the_embed(chain):
    chain.llm.content = "[verse]\nuna *riga* con_underscore\nseconda `riga` lunga abbastanza"
    it = await run(chain)
    description = final(it)["embed"].description
    assert "\\*riga\\*" in description and "con\\_underscore" in description and "\\`riga\\`" in description
