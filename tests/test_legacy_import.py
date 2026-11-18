"""Test dell'import una tantum dei vecchi JSON (soundboard, speaker, modelli RVC) dentro SQLite."""

import json
from types import SimpleNamespace

import pytest

import cogs
import legacy_import
import storage
from audio_samples import wav_bytes, write
from database import Database


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cogs, "BASE_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "RVC_MODELS_DIR", tmp_path / "models")
    db = await Database.open(tmp_path / "t.sqlite3")
    yield SimpleNamespace(db=db, data=tmp_path / "data", models=tmp_path / "models", tmp=tmp_path,
                          rvc_index=tmp_path / "rvc_index.json")
    await db.aclose()


def put_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


async def run(env):
    return await legacy_import.import_legacy_json(env.db, env.data, env.models, env.rvc_index)


async def test_everything_is_imported_and_the_old_files_are_set_aside(env):
    write(env.data / "7" / "soundboard" / "clap.wav", wav_bytes())
    sb = put_json(env.data / "7" / "soundboard" / "index.json", {"Clap": "clap.wav"})
    write(env.data / "7" / "speakers" / "bob_1.wav", wav_bytes(2))
    write(env.data / "7" / "speakers" / "eve_1.wav", wav_bytes(2))
    sp = put_json(env.data / "7" / "speakers" / "index.json", {"robert": "bob_1.wav", "eve": "eve_1.wav"})
    al = put_json(env.data / "7" / "speakers" / "alias.json", {"bob": "robert"})
    write(env.models / "voce1" / "m.pth", b"x")
    rv = put_json(env.rvc_index, {"Voce Uno": "voce1"})

    result = await run(env)
    assert (result["sounds"], result["voices"], result["models"], result["skipped"]) == (1, 2, 1, [])

    sounds = await storage.list_sounds(env.db, 7)
    assert [(s["name"], s["filename"], s["missing"]) for s in sounds] == [("Clap", "clap.wav", False)]
    voices = {v["name"]: v for v in await storage.list_voices(env.db, 7)}
    assert voices["robert"]["source_name"] == "bob"            # l'alias diventa il nome originale della registrazione
    assert voices["eve"]["source_name"] == "eve" and voices["eve"]["duration"] == pytest.approx(2.0, abs=0.01)
    assert (await storage.list_rvc_models(env.db))[0]["folder"] == "voce1"
    assert "legacy.import" in [a["action"] for a in await storage.list_audit(env.db)]

    for original in (sb, sp, al, rv):                           # mai cancellati: rinominati
        assert not original.exists() and original.with_name(original.name + ".migrated").exists()


async def test_second_run_does_nothing(env):
    write(env.data / "7" / "soundboard" / "clap.wav", wav_bytes())
    put_json(env.data / "7" / "soundboard" / "index.json", {"Clap": "clap.wav"})
    await run(env)
    again = await run(env)
    assert (again["sounds"], again["voices"], again["models"]) == (0, 0, 0)
    assert len(await storage.list_sounds(env.db)) == 1


async def test_reimporting_a_restored_file_does_not_duplicate_anything(env):
    write(env.data / "7" / "soundboard" / "clap.wav", wav_bytes())
    path = put_json(env.data / "7" / "soundboard" / "index.json", {"Clap": "clap.wav"})
    await run(env)
    put_json(path, {"Clap": "clap.wav"})                        # l'utente rimette il vecchio file
    assert (await run(env))["sounds"] == 0
    assert len(await storage.list_sounds(env.db)) == 1


async def test_entries_with_missing_or_dangerous_files_are_skipped_and_reported(env):
    write(env.data / "7" / "soundboard" / "ok.wav", wav_bytes())
    write(env.data / "secret.wav", wav_bytes())
    put_json(env.data / "7" / "soundboard" / "index.json",
             {"Ok": "ok.wav", "Mancante": "nope.wav", "Evil": "../../secret.wav", "Assoluto": "/etc/passwd"})
    write(env.models / "reale" / "m.pth", b"x")
    put_json(env.rvc_index, {"Reale": "reale", "Fuori": "../data", "Assente": "assente"})

    result = await run(env)
    assert (result["sounds"], result["models"]) == (1, 1)
    assert len(result["skipped"]) == 5
    assert [s["name"] for s in await storage.list_sounds(env.db)] == ["Ok"]
    assert [m["name"] for m in await storage.list_rvc_models(env.db)] == ["Reale"]


async def test_a_corrupt_file_is_left_in_place_and_does_not_block_the_others(env):
    write(env.data / "7" / "soundboard" / "clap.wav", wav_bytes())
    bad = put_json(env.data / "7" / "soundboard" / "index.json", "{rotto")
    write(env.data / "8" / "soundboard" / "a.wav", wav_bytes())
    put_json(env.data / "8" / "soundboard" / "index.json", {"A": "a.wav"})
    put_json(env.rvc_index, ["non", "un", "oggetto"])

    result = await run(env)
    assert result["sounds"] == 1 and bad.exists() and env.rvc_index.exists()
    assert [s["guild_id"] for s in await storage.list_sounds(env.db)] == [8]


async def test_a_corrupt_alias_file_does_not_block_the_speakers(env):
    write(env.data / "7" / "speakers" / "bob_1.wav", wav_bytes())
    put_json(env.data / "7" / "speakers" / "index.json", {"bob": "bob_1.wav"})
    alias = put_json(env.data / "7" / "speakers" / "alias.json", "{rotto")
    assert (await run(env))["voices"] == 1 and alias.exists()


async def test_invalid_names_and_non_server_folders_are_ignored(env):
    write(env.data / "7" / "soundboard" / "a.wav", wav_bytes())
    put_json(env.data / "7" / "soundboard" / "index.json", {"   ": "a.wav", "x" * 200: "a.wav", "Buono": "a.wav"})
    write(env.data / "global" / "soundboard" / "b.wav", wav_bytes())
    put_json(env.data / "global" / "soundboard" / "index.json", {"Globale": "b.wav"})    # non è un id server
    result = await run(env)
    assert result["sounds"] == 1
    assert [s["name"] for s in await storage.list_sounds(env.db)] == ["Buono"]


async def test_nothing_to_import_is_fine(env):
    assert (await run(env))["sounds"] == 0
