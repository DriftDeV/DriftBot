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
from fake_servers import FakeAceStep, FakeAnthropic, FakeOllama
from fakes import FakeGuild, FakeInteraction, make_channel
from text_llm import ClaudeConfig, LLMConfig, OllamaConfig

pytestmark = pytest.mark.usefixtures("instant_playback")


@pytest.fixture
async def chain():
    events = []
    acestep, ollama = FakeAceStep(events), FakeOllama(events)
    servers = [TestServer(acestep.app()), TestServer(ollama.app())]
    for server in servers:
        await server.start_server()
    acestep.url = str(servers[0].make_url("")).rstrip("/")
    ollama.url = str(servers[1].make_url("")).rstrip("/")

    llm = LLMConfig(ollama=OllamaConfig(base_url=ollama.url, timeout=2, unload_timeout=0.5, poll_interval=0.01))
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
    await chain.cog.ai_music.callback(chain.cog, it, prompt, "ace", durata, testo, lingua, strumentale)
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
    assert body["lyrics"].startswith("[Verse]") and "Luci di città" in body["lyrics"]
    assert body["vocal_language"] == "it"

    embed = final(it)["embed"]
    assert "Luci di città" in embed.description                        # il testo è mostrato all'utente
    assert "testo scritto dall'AI" in embed_fields(it)["Dettagli"]
    assert "⚠️ Nota" not in embed_fields(it)
    assert chain.guild.voice_client.played                              # e il brano è suonato in vocale

    user_message = chain.llm.chat_requests[0]["messages"][1]["content"]
    assert "ballata malinconica sul mare" in user_message and "100 seconds" in user_message
    texts = [e.get("content") or "" for e in it.edits]
    assert any("preparando il testo" in t for t in texts) and any("componendo" in t for t in texts)


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
    chain.config.llm.ollama.unload_timeout = 0.1
    chain.llm.sticky = chain.llm.ignore_explicit = True
    it = await run(chain)
    assert final(it)["embed"].title == "🎵 Musica generata"             # non resta bloccato per sempre


HEADER = ("CAPTION: Intimate acoustic folk ballad, fingerpicked guitar, soft piano, warm female voice, airy and tender\n"
          "BPM: 78\nKEY: D major\nTIME: 3\n\n")
USER_LYRICS = "il mio testo\nsecondo verso\n\nrefrain finale\nsempre uguale"


async def test_instrumental_skips_the_llm(chain):
    it = await run(chain, strumentale=True)
    assert chain.ace.submitted[-1]["lyrics"] == "[Instrumental]"
    assert "strumentale" in embed_fields(it)["Dettagli"]
    assert chain.llm.chat_requests == [] and "llm_chat_start" not in chain.events


async def test_user_lyrics_get_caption_metadata_and_tags_but_keep_their_words(chain):
    chain.llm.content = HEADER + "[Verse]\nil mio testo\nsecondo verso\n\n[Chorus - tender]\nrefrain finale\nsempre uguale"
    it = await run(chain, prompt="una ninna nanna dolce", testo=USER_LYRICS)
    body = chain.ace.submitted[-1]
    assert body["lyrics"] == "[Verse]\nil mio testo\nsecondo verso\n\n[Chorus - tender]\nrefrain finale\nsempre uguale"
    assert body["prompt"].startswith("Intimate acoustic folk ballad")
    assert (body["bpm"], body["key_scale"], body["time_signature"]) == (78, "D Major", "3")
    assert "con testo" in embed_fields(it)["Dettagli"] and "⚠️ Nota" not in embed_fields(it)
    sent = chain.llm.chat_requests[0]["messages"]
    assert "never translate" in sent[0]["content"].lower() or "Never translate" in sent[0]["content"]
    assert USER_LYRICS in sent[1]["content"]


async def test_if_the_llm_touches_the_words_the_original_text_is_kept(chain):
    chain.llm.content = HEADER + "[Verse]\nil mio testo bellissimo\nsecondo verso\n\n[Chorus]\nrefrain finale\nsempre uguale"
    await run(chain, testo=USER_LYRICS)
    body = chain.ace.submitted[-1]
    assert body["lyrics"] == USER_LYRICS                         # parole e righe identiche, senza i tag dell'LLM
    assert body["bpm"] == 78 and body["prompt"].startswith("Intimate acoustic")   # caption e metadati restano


async def test_user_lyrics_survive_an_llm_failure_and_are_not_turned_instrumental(chain):
    chain.llm.chat_status = 500
    it = await run(chain, prompt="ballata sul mare", testo=USER_LYRICS)
    body = chain.ace.submitted[-1]
    assert body["lyrics"] == USER_LYRICS and body["prompt"] == "ballata sul mare"
    assert not {"bpm", "key_scale", "time_signature"} & set(body)
    assert "Uso il tuo prompt" in embed_fields(it)["⚠️ Nota"] and "con testo" in embed_fields(it)["Dettagli"]


async def test_lyrics_and_instrumental_together_are_rejected(chain):
    it = await run(chain, testo="un testo", strumentale=True)
    assert "in contrasto" in it.last and it.sent[-1][1]["ephemeral"]
    assert chain.ace.submitted == [] and chain.llm.chat_requests == []


async def test_llm_disabled_means_instrumental(chain):
    chain.config.llm.enabled = False
    it = await run(chain)
    assert chain.ace.submitted[0]["lyrics"] == "[Instrumental]" and chain.llm.chat_requests == []
    assert "⚠️ Nota" not in embed_fields(it)


async def test_caption_and_metadata_from_the_llm_reach_acestep(chain):
    chain.llm.content = (
        "CAPTION: Western ballad, fingerpicked acoustic guitar, harmonica, warm male baritone, dusty\n"
        "BPM: 92\nKEY: G major\nTIME: 4\n\n[Intro]\n\n[Verse]\nluci di città\npasso lento\n\n[Chorus]\ncanto con te\nresta qui"
    )
    it = await run(chain, prompt="una canzone su un cowboy")
    body = chain.ace.submitted[0]
    assert body["prompt"].startswith("Western ballad, fingerpicked")      # caption sonora, non la richiesta grezza
    assert (body["bpm"], body["key_scale"], body["time_signature"]) == (92, "G Major", "4")
    assert "CAPTION" not in body["lyrics"] and body["lyrics"].startswith("[Intro]")
    assert body["use_cot_language"] is False
    assert {f.name: f.value for f in final(it)["embed"].fields}["Prompt"] == "una canzone su un cowboy"   # all'utente resta la sua frase


async def test_without_a_usable_header_the_user_prompt_and_server_metadata_are_kept(chain):
    await run(chain, prompt="ballata malinconica sul mare")
    body = chain.ace.submitted[0]
    assert body["prompt"] == "ballata malinconica sul mare"
    assert not {"bpm", "key_scale", "time_signature"} & set(body)


# ------------------------------------------------------------ durata e lingua

async def test_default_duration_is_100_seconds_not_the_maximum(chain):
    await run(chain, durata=None)
    assert chain.ace.submitted[-1]["audio_duration"] == 100

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
    assert lyrics.startswith("[Verse]") and "[Chorus]" in lyrics
    assert not any(junk in lyrics for junk in ("Certo", "think", "**", "##"))


# ------------------------------------------------- se l'LLM non va, il brano si fa lo stesso

@pytest.mark.parametrize("setup, expected", [
    (lambda c: setattr(c.llm, "chat_status", 404), "ollama pull qwen2.5:7b"),
    (lambda c: setattr(c.llm, "chat_status", 500), "HTTP 500"),
    (lambda c: setattr(c.llm, "content", "boh"), "utilizzabile"),
    (lambda c: (setattr(c.config.llm.ollama, "timeout", 0.1), setattr(c.llm, "delay", 0.5)), "in tempo"),
    (lambda c: setattr(c.config.llm.ollama, "base_url", "http://127.0.0.1:1"), "non è raggiungibile"),
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


# ============================================================ provider Claude (key nel .env)

CLAUDE_KEY = "sk-ant-test-chiave-segretissima"
CLAUDE_LYRICS = "[verse]\nOnde di Claude sul mare\nPortano via la sera\n[chorus]\nCanta con me stanotte\nIl vento ci risponde"


@pytest.fixture
async def chain_claude():
    """Come `chain`, ma con ANTHROPIC_API_KEY presente: Ollama è configurato ma NON deve essere usato."""
    events = []
    acestep, ollama, claude = FakeAceStep(events), FakeOllama(events), FakeAnthropic(events)
    claude.content = CLAUDE_LYRICS
    servers = [TestServer(f.app()) for f in (acestep, ollama, claude)]
    for server in servers:
        await server.start_server()
    acestep.url, ollama.url, claude.url = (str(server.make_url("")).rstrip("/") for server in servers)

    llm = LLMConfig(
        ollama=OllamaConfig(base_url=ollama.url, timeout=2, unload_timeout=0.5, poll_interval=0.01),
        claude=ClaudeConfig(api_key=CLAUDE_KEY, base_url=claude.url, max_retries=0, timeout=5),
    )
    config = AceStepConfig(base_url=acestep.url, poll_interval=0.01, timeout=5, max_seconds=180, llm=llm)
    cog = AceStepMusic(SimpleNamespace(), config)
    guild = FakeGuild(7)
    guild.filesize_limit = 10_000_000
    channel = make_channel(guild)
    yield SimpleNamespace(cog=cog, ace=acestep, llm=ollama, claude=claude, events=events,
                          guild=guild, channel=channel, config=config)
    await cog.cog_unload()
    for server in servers:
        await server.close()


async def test_claude_writes_the_lyrics_when_the_key_is_present(chain_claude):
    chain_claude.ace.running_polls = 1
    it = await run(chain_claude)

    body = chain_claude.ace.submitted[0]
    assert body["lyrics"] == CLAUDE_LYRICS.replace("[verse]", "[Verse]").replace("[chorus]", "[Chorus]")
    assert body["vocal_language"] == "it"
    assert "Onde di Claude" in final(it)["embed"].description
    assert "testo scritto dall'AI (Claude claude-opus-5-5)" in embed_fields(it)["Dettagli"]
    assert any("Claude claude-opus-5-5" in (e.get("content") or "") for e in it.edits)

    # il flusso locale NON è stato toccato: niente chat, niente controllo della VRAM
    assert chain_claude.llm.chat_requests == [] and chain_claude.llm.ps_calls == 0
    assert chain_claude.events.index("claude_call") < chain_claude.events.index("ace_release")
    request = chain_claude.claude.requests[0]["body"]
    assert "ballata malinconica sul mare" in request["messages"][0]["content"] and "100 seconds" in request["messages"][0]["content"]


async def test_without_the_key_the_local_flow_is_used(chain_claude):
    chain_claude.config.llm.claude.api_key = ""                 # la key sparisce dal .env
    it = await run(chain_claude)
    assert chain_claude.claude.requests == [] and len(chain_claude.llm.chat_requests) == 1
    assert "Luci di città" in chain_claude.ace.submitted[0]["lyrics"]
    assert "testo scritto dall'AI (qwen2.5:7b)" in embed_fields(it)["Dettagli"]


async def test_claude_lyrics_are_written_outside_the_gpu_lock(chain_claude):
    """Claude non usa la GPU locale: mentre ACE-Step lavora per un utente, il testo dell'altro si scrive già."""
    chain_claude.ace.gate = asyncio.Event()
    first = asyncio.create_task(run(chain_claude, user_id=1))
    while "ace_release" not in chain_claude.events:
        await asyncio.sleep(0.01)
    second = asyncio.create_task(run(chain_claude, user_id=2))
    while chain_claude.events.count("claude_call") < 2:
        await asyncio.sleep(0.01)

    # il testo del secondo è pronto mentre il brano del primo è ancora in lavorazione...
    assert "ace_done" not in chain_claude.events and chain_claude.events.count("ace_release") == 1
    chain_claude.ace.gate.set()
    for task in (first, second):
        assert final(await task)["embed"].title == "🎵 Musica generata"
    # ...ma ACE-Step resta uno alla volta
    releases = [i for i, e in enumerate(chain_claude.events) if e == "ace_release"]
    assert len(releases) == 2 and releases[1] > chain_claude.events.index("ace_done")
    assert chain_claude.llm.chat_requests == []


@pytest.mark.parametrize("setup, expected", [
    (lambda c: (setattr(c.claude, "status", 401), setattr(c.claude, "error_type", "authentication_error")), "API key"),
    (lambda c: (setattr(c.claude, "status", 529), setattr(c.claude, "error_type", "overloaded_error")), "temporaneamente"),
    (lambda c: setattr(c.claude, "stop_reason", "refusal"), "rifiutato"),
    (lambda c: setattr(c.claude, "content", "boh"), "utilizzabile"),
])
async def test_claude_failure_gives_an_instrumental_track_and_never_falls_back_to_local(chain_claude, setup, expected):
    setup(chain_claude)
    it = await run(chain_claude)
    assert chain_claude.ace.submitted[0]["lyrics"] == "[Instrumental]"
    assert final(it)["embed"].title == "🎵 Musica generata"
    note = embed_fields(it)["⚠️ Nota"]
    assert expected in note and "strumentale" in note.lower()
    assert CLAUDE_KEY not in note and "boom detail" not in note
    # con la key presente non si ripiega in silenzio sul locale (VRAM imprevista, key sbagliata nascosta)
    assert chain_claude.llm.chat_requests == [] and chain_claude.llm.ps_calls == 0


async def test_no_paid_call_when_the_llm_is_not_needed(chain_claude):
    await run(chain_claude, strumentale=True)
    chain_claude.config.llm.enabled = False
    await run(chain_claude, testo="[verse]\nil mio testo\nsecondo verso")      # LLM spento: testo identico
    await run(chain_claude)
    assert chain_claude.claude.requests == [] and chain_claude.events.count("claude_call") == 0
    assert [b["lyrics"] for b in chain_claude.ace.submitted] == [
        "[Instrumental]", "[verse]\nil mio testo\nsecondo verso", "[Instrumental]"]


async def test_user_lyrics_cost_one_claude_call_and_stay_unchanged(chain_claude):
    await run(chain_claude, testo="[verse]\nil mio testo\nsecondo verso")
    assert len(chain_claude.claude.requests) == 1
    assert chain_claude.ace.submitted[-1]["lyrics"] == "[verse]\nil mio testo\nsecondo verso"   # Claude ne ha risposto un altro
