"""Test del livello LLM: scelta del provider (Claude con key, Ollama senza), Ollama e Claude."""

import logging
import sys

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

import text_llm
from fake_servers import FakeAnthropic, FakeOllama
from lyrics_llm import LyricsWriter
from text_llm import (
    ClaudeConfig,
    ClaudeGenerator,
    LLMConfig,
    LLMError,
    OllamaConfig,
    OllamaGenerator,
    build_generator,
)

SECRET_KEY = "sk-ant-test-chiave-segretissima"
ENV_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", "CLAUDE_EFFORT", "CLAUDE_TIMEOUT", "CLAUDE_REFUSAL_FALLBACK",
            "ANTHROPIC_BASE_URL", "LYRICS_LLM_ENABLED", "LYRICS_LLM_URL", "LYRICS_LLM_MODEL", "LYRICS_LLM_TIMEOUT")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    text_llm.reset_fallback_state()
    yield
    text_llm.reset_fallback_state()


# ------------------------------------------------------------- scelta del provider

def test_provider_depends_on_the_api_key():
    assert LLMConfig().provider == "ollama"                                  # nessuna key: flusso locale
    assert LLMConfig(claude=ClaudeConfig(api_key=SECRET_KEY)).provider == "claude"
    assert LLMConfig(enabled=False, claude=ClaudeConfig(api_key=SECRET_KEY)).provider is None


def test_build_generator_returns_the_right_provider():
    assert isinstance(build_generator(LLMConfig(), None), OllamaGenerator)
    claude = build_generator(LLMConfig(claude=ClaudeConfig(api_key=SECRET_KEY)), None)
    assert isinstance(claude, ClaudeGenerator) and claude.label == "Claude claude-opus-5-5"
    assert build_generator(LLMConfig(enabled=False), None) is None
    assert claude.uses_local_gpu is False and OllamaGenerator(OllamaConfig(), None).uses_local_gpu is True


def test_provider_from_env_follows_the_key_in_the_environment(monkeypatch):
    assert LLMConfig.from_env().provider == "ollama"
    monkeypatch.setenv("ANTHROPIC_API_KEY", f"  {SECRET_KEY} ")
    assert LLMConfig.from_env().provider == "claude" and LLMConfig.from_env().claude.api_key == SECRET_KEY
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")                           # key vuota = assente
    assert LLMConfig.from_env().provider == "ollama"


def test_claude_config_from_env(monkeypatch):
    default = ClaudeConfig.from_env()
    assert (default.model, default.effort, default.refusal_fallback, default.timeout) == ("claude-opus-5-5", "low", True, 120)

    monkeypatch.setenv("CLAUDE_MODEL", " claude-haiku-5-5 ")
    monkeypatch.setenv("CLAUDE_EFFORT", "HIGH")
    monkeypatch.setenv("CLAUDE_TIMEOUT", "abc")
    monkeypatch.setenv("CLAUDE_REFUSAL_FALLBACK", "false")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy:9000")
    config = ClaudeConfig.from_env()
    assert (config.model, config.effort, config.timeout) == ("claude-haiku-5-5", "high", 120)
    assert config.refusal_fallback is False and config.base_url == "http://proxy:9000"

    monkeypatch.setenv("CLAUDE_EFFORT", "")                                  # vuoto = non inviare effort
    assert ClaudeConfig.from_env().effort == ""
    monkeypatch.setenv("CLAUDE_EFFORT", "ultra")                             # non valido = default
    assert ClaudeConfig.from_env().effort == "low"
    monkeypatch.setenv("CLAUDE_TIMEOUT", "99999")
    assert ClaudeConfig.from_env().timeout == 600


def test_ollama_and_enabled_config_from_env(monkeypatch):
    default = LLMConfig.from_env()
    assert default.enabled and (default.ollama.base_url, default.ollama.model) == ("http://127.0.0.1:11434", "qwen2.5:7b")
    monkeypatch.setenv("LYRICS_LLM_ENABLED", "False")
    monkeypatch.setenv("LYRICS_LLM_URL", " http://gpu:11434/ ")
    monkeypatch.setenv("LYRICS_LLM_MODEL", "  ")                             # vuoto -> default
    monkeypatch.setenv("LYRICS_LLM_TIMEOUT", "abc")                          # non valido -> default
    config = LLMConfig.from_env()
    assert config.enabled is False and config.ollama.base_url == "http://gpu:11434"
    assert config.ollama.model == "qwen2.5:7b" and config.ollama.timeout == 180
    monkeypatch.setenv("LYRICS_LLM_TIMEOUT", "99999")
    assert LLMConfig.from_env().ollama.timeout == 1800


def test_model_name_normalization():
    assert text_llm._normalize_model_name("Qwen2.5") == "qwen2.5:latest"
    assert text_llm._normalize_model_name("qwen2.5:7b") == "qwen2.5:7b"


# ----------------------------------------------------------------------------- Claude

@pytest.fixture
async def anthropic_server():
    fake = FakeAnthropic()
    server = TestServer(fake.app())
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    generators = []

    def make(**overrides):
        options = dict(api_key=SECRET_KEY, base_url=fake.url, max_retries=0, timeout=5)
        config = ClaudeConfig(**{**options, **overrides})
        generator = ClaudeGenerator(config)
        generators.append(generator)
        return generator

    fake.make = make
    yield fake
    for generator in generators:
        await generator.close()
    await server.close()


async def test_claude_request_follows_the_current_api_contract(anthropic_server):
    generator = anthropic_server.make()
    text = await generator.generate("SISTEMA", "UTENTE")
    assert text == FakeAnthropic.GOOD

    request = anthropic_server.requests[0]
    body, headers = request["body"], request["headers"]
    # l'SDK manda la key come Bearer (o x-api-key, a seconda della versione): entrambe sono valide
    assert SECRET_KEY in (headers.get("x-api-key"), headers.get("authorization", "").removeprefix("Bearer "))
    assert "anthropic-version" in headers
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 8000
    assert body["system"] == "SISTEMA" and body["messages"] == [{"role": "user", "content": "UTENTE"}]
    assert body["output_config"] == {"effort": "low"}
    # su Opus 5.5 / Haiku 5.5 questi parametri danno errore 400: non vanno mai inviati
    for forbidden in ("temperature", "top_p", "top_k", "thinking"):
        assert forbidden not in body
    # fallback lato server sui rifiuti dei classificatori di sicurezza, abilitato di default
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]


async def test_claude_text_comes_from_text_blocks_only(anthropic_server):
    anthropic_server.blocks = [{"type": "thinking", "thinking": "", "signature": "x"},
                               {"type": "text", "text": "[verse]\nuno due"}, {"type": "text", "text": "\ntre quattro"}]
    assert await anthropic_server.make().generate("s", "u") == "[verse]\nuno due\ntre quattro"


async def test_optional_parameters_can_be_switched_off(anthropic_server):
    await anthropic_server.make(effort="", refusal_fallback=False, model="claude-haiku-5-5").generate("s", "u")
    request = anthropic_server.requests[0]
    assert "output_config" not in request["body"] and "fallbacks" not in request["body"]
    assert request["body"]["model"] == "claude-haiku-5-5"
    assert "anthropic-beta" not in request["headers"] and "beta" not in request["query"]


async def test_fallback_is_disabled_once_the_server_rejects_it(anthropic_server):
    anthropic_server.reject_fallbacks = True
    generator = anthropic_server.make()
    assert await generator.generate("s", "u") == FakeAnthropic.GOOD          # ripete da solo senza fallback
    assert ["fallbacks" in r["body"] for r in anthropic_server.requests] == [True, False]

    await anthropic_server.make().generate("s", "u")                         # e non ci riprova più
    assert "fallbacks" not in anthropic_server.requests[-1]["body"] and len(anthropic_server.requests) == 3


async def test_unrelated_400_is_not_mistaken_for_a_fallback_problem(anthropic_server):
    anthropic_server.status, anthropic_server.error_type = 400, "invalid_request_error"
    anthropic_server.error_message = "output_config.effort: not supported by this model"
    with pytest.raises(LLMError, match="impostazioni del modello"):
        await anthropic_server.make().generate("s", "u")
    assert len(anthropic_server.requests) == 1 and text_llm._fallbacks_unsupported is False


@pytest.mark.parametrize("status, error_type, expected", [
    (401, "authentication_error", "API key"),
    (403, "permission_error", "permessi"),
    (404, "not_found_error", "claude-opus-5-5"),
    (429, "rate_limit_error", "Limite di richieste"),
    (500, "api_error", "temporaneamente"),
    (529, "overloaded_error", "temporaneamente"),
])
async def test_claude_errors_are_mapped_without_leaking_details(anthropic_server, caplog, status, error_type, expected):
    anthropic_server.status, anthropic_server.error_type = status, error_type
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LLMError) as error:
            await anthropic_server.make().generate("s", "u")
    message = str(error.value)
    assert expected in message
    assert "boom detail" not in message and SECRET_KEY not in message
    assert SECRET_KEY not in caplog.text                                      # la key non finisce mai nei log


async def test_claude_out_of_credit_and_slow_and_unreachable(anthropic_server):
    anthropic_server.status, anthropic_server.error_type = 400, "invalid_request_error"
    anthropic_server.error_message = "Your credit balance is too low to access the Anthropic API."
    with pytest.raises(LLMError, match="credito"):
        await anthropic_server.make().generate("s", "u")

    anthropic_server.status, anthropic_server.delay = 200, 0.6
    with pytest.raises(LLMError, match="in tempo"):
        await anthropic_server.make(timeout=0.2).generate("s", "u")

    unreachable = ClaudeGenerator(ClaudeConfig(api_key=SECRET_KEY, base_url="http://127.0.0.1:1", max_retries=0, timeout=2))
    with pytest.raises(LLMError, match="non è raggiungibile"):
        await unreachable.generate("s", "u")
    await unreachable.close()


async def test_claude_refusal_and_empty_answers(anthropic_server):
    anthropic_server.stop_reason = "refusal"
    with pytest.raises(LLMError, match="rifiutato"):
        await anthropic_server.make().generate("s", "u")

    anthropic_server.stop_reason, anthropic_server.blocks = "end_turn", [{"type": "text", "text": "  "}]
    with pytest.raises(LLMError, match="nessun testo"):
        await anthropic_server.make().generate("s", "u")

    anthropic_server.stop_reason = "max_tokens"                              # il thinking ha consumato tutti i token
    with pytest.raises(LLMError, match="esaurito i token"):
        await anthropic_server.make().generate("s", "u")


async def test_claude_without_the_sdk_installed_gives_a_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)                      # import anthropic -> ImportError
    with pytest.raises(LLMError, match="pip install anthropic"):
        await ClaudeGenerator(ClaudeConfig(api_key=SECRET_KEY)).generate("s", "u")


async def test_claude_needs_no_local_cleanup(anthropic_server):
    generator = anthropic_server.make()
    await generator.release()                                                # non c'è nulla da scaricare
    await generator.close()
    await generator.generate("s", "u")
    await generator.close()
    await generator.close()                                                  # idempotente


async def test_lyrics_writer_works_with_claude(anthropic_server):
    text = await LyricsWriter(anthropic_server.make()).write("ballata sul mare", 90, "en")
    assert text.startswith("[Verse]") and "[Chorus]" in text
    request = anthropic_server.requests[0]["body"]
    assert "English" in request["system"] and "ballata sul mare" in request["messages"][0]["content"]


# ----------------------------------------------------------------------------- Ollama

@pytest.fixture
async def ollama():
    fake = FakeOllama()
    server = TestServer(fake.app())
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    session = aiohttp.ClientSession()
    config = OllamaConfig(base_url=fake.url, timeout=2, unload_timeout=0.5, poll_interval=0.01)
    fake.generator = OllamaGenerator(config, session)
    fake.writer = LyricsWriter(fake.generator)
    fake.config = config
    yield fake
    await session.close()
    await server.close()


async def test_ollama_sends_the_documented_request_and_returns_clean_lyrics(ollama):
    text = await ollama.writer.write("ballata sul mare", 90, "it")
    assert text.startswith("[Verse]") and "[Chorus]" in text
    body = ollama.chat_requests[0]
    assert body["model"] == "qwen2.5:7b" and body["stream"] is False
    assert body["keep_alive"] == 0                              # scarica subito dopo la risposta
    assert body["options"]["num_ctx"] == 2048                   # contesto piccolo: poca VRAM
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "ballata sul mare" in body["messages"][1]["content"]


async def test_ollama_errors_are_mapped_and_the_model_is_still_unloaded(ollama):
    ollama.chat_status = 404
    with pytest.raises(LLMError, match="ollama pull qwen2.5:7b"):
        await ollama.writer.write("x y z", 60, "it")

    ollama.chat_status, ollama.sticky = 500, True
    with pytest.raises(LLMError, match="HTTP 500"):
        await ollama.writer.write("x y z", 60, "it")
    assert ollama.explicit_unloads == 1 and not ollama.loaded   # scaricato anche dopo l'errore

    ollama.chat_status, ollama.content = 200, "niente di utile"
    with pytest.raises(LLMError, match="utilizzabile"):
        await ollama.writer.write("x y z", 60, "it")


async def test_ollama_timeout_still_unloads(ollama):
    ollama.config.timeout = 0.1
    ollama.delay, ollama.sticky = 0.5, True
    with pytest.raises(LLMError, match="in tempo"):
        await ollama.writer.write("x y z", 60, "it")
    assert not ollama.loaded or await ollama.generator.ensure_unloaded()
    await ollama.generator.ensure_unloaded()
    assert not ollama.loaded


async def test_ollama_waits_for_the_model_to_leave_memory(ollama):
    ollama.linger_polls = 4
    await ollama.writer.write("x y z", 60, "it")
    assert not ollama.loaded and ollama.ps_calls >= 2


async def test_ollama_gives_up_after_timeout_without_raising(ollama):
    ollama.sticky = ollama.ignore_explicit = True
    await ollama.writer.write("x y z", 60, "it")                # non solleva anche se non si scarica
    assert ollama.loaded
    assert await ollama.generator.ensure_unloaded() is False


async def test_ollama_unreachable(ollama):
    ollama.config.base_url = "http://127.0.0.1:1"
    with pytest.raises(LLMError, match="non è raggiungibile"):
        await ollama.writer.write("x y z", 60, "it")
    assert await ollama.generator.ensure_unloaded() is True     # non verificabile: non blocca
