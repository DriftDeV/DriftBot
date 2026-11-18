"""Test dell'archivio: suoni, voci, modelli RVC, server (con SQLite vero e cartelle temporanee)."""

import asyncio
import itertools
import sqlite3
from types import SimpleNamespace

import pytest

import cogs
import storage
from audio_samples import FLAC, M4A, MP3, OGG, wav_bytes, write, zip_bytes
from database import Database
from storage import Duplicate, InvalidInput, NotFound

_counter = itertools.count()


@pytest.fixture
async def st(tmp_path, monkeypatch):
    monkeypatch.setattr(cogs, "BASE_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "RVC_MODELS_DIR", tmp_path / "models")
    db = await Database.open(tmp_path / "t.sqlite3")
    yield SimpleNamespace(db=db, tmp=tmp_path)
    await db.aclose()


def upload(st, data: bytes, name="up.wav"):
    return write(st.tmp / "uploads" / f"{next(_counter)}-{name}", data)


def files_in(path):
    return sorted(p.name for p in path.iterdir()) if path.exists() else []


async def actions(st):
    return [r["action"] for r in await storage.list_audit(st.db)]


# ------------------------------------------------------------------------- funzioni pure

def test_sniff_audio_recognises_content_not_extension(tmp_path):
    for kind, data in (("wav", wav_bytes()), ("mp3", MP3), ("ogg", OGG), ("flac", FLAC), ("m4a", M4A)):
        assert storage.sniff_audio(write(tmp_path / "x.bin", data)) == kind
    for bad in (b"", b"MZ\x90\x00 exe", b"<html>", b"#!/bin/sh\n", b"PK\x03\x04 zip"):
        assert storage.sniff_audio(write(tmp_path / "bad.wav", bad)) is None     # .wav ma non audio
    assert storage.sniff_audio(tmp_path / "inesistente") is None


def test_clean_name_rules():
    assert storage.clean_name("  Ciao   mondo \n") == "Ciao mondo"
    assert storage.clean_name("a\x00b\x07c") == "a b c"
    assert storage.clean_name("🎺 Tromba") == "🎺 Tromba"
    for bad in ("", "   ", "\n\t", "x" * 101, None, 5):
        with pytest.raises(InvalidInput):
            storage.clean_name(bad)
    assert len(storage.clean_name("x" * 100)) == 100


def test_parse_id_accepts_only_positive_integers():
    assert storage.parse_id("12") == 12 and storage.parse_id(7) == 7 and storage.parse_id(" 3 ") == 3
    for bad in ("clap.wav", "../../x", "-1", "0", "", None, "1.5", "9" * 30, "1; DROP TABLE sounds"):
        assert storage.parse_id(bad) is None


# ------------------------------------------------------------------------------ suoni

async def test_add_sound_moves_the_file_and_records_it(st):
    src = upload(st, wav_bytes())
    row = await storage.add_sound(st.db, 7, "  Applauso ", src, actor="admin")
    assert row["name"] == "Applauso" and row["guild_id"] == 7 and row["size"] > 0
    assert not src.exists()                                     # spostato, non copiato
    assert files_in(storage.sounds_dir(7)) == [row["filename"]] and row["filename"].endswith(".wav")
    assert (await actions(st))[0] == "sound.add"
    assert (await storage.list_audit(st.db))[0]["actor"] == "admin"


async def test_global_sounds_live_in_their_own_folder_and_are_usable_everywhere(st):
    await storage.add_sound(st.db, storage.GLOBAL, "Airhorn", upload(st, MP3, "a.mp3"))
    await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    await storage.add_sound(st.db, 8, "Altro", upload(st, wav_bytes()))
    assert len(files_in(storage.sounds_dir(storage.GLOBAL))) == 1
    assert [r["name"] for r in await storage.list_sounds_for_guild(st.db, 7)] == ["Airhorn", "Clap"]
    assert [r["name"] for r in await storage.list_sounds_for_guild(st.db, 9)] == ["Airhorn"]


async def test_invalid_uploads_are_rejected_and_the_temp_file_removed(st, monkeypatch):
    cases = [(b"", "vuoto"), (b"questo non e' audio", "non riconosciuto")]
    for data, expected in cases:
        src = upload(st, data)
        with pytest.raises(InvalidInput, match=expected if expected != "vuoto" else "vuoto"):
            await storage.add_sound(st.db, 7, "x", src)
        assert not src.exists()
    monkeypatch.setattr(storage, "MAX_SOUND_BYTES", 100)
    with pytest.raises(InvalidInput, match="limite"):
        await storage.add_sound(st.db, 7, "x", upload(st, wav_bytes(2)))
    with pytest.raises(InvalidInput, match="vuoto"):
        await storage.add_sound(st.db, 7, "   ", upload(st, wav_bytes()))
    assert files_in(storage.sounds_dir(7)) == [] and await storage.list_sounds(st.db) == []


async def test_duplicate_names_are_refused_without_leaving_orphan_files(st):
    await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    with pytest.raises(Duplicate, match="clap"):
        await storage.add_sound(st.db, 7, "clap", upload(st, wav_bytes()))      # maiuscole/minuscole non contano
    assert len(files_in(storage.sounds_dir(7))) == 1
    await storage.add_sound(st.db, 8, "Clap", upload(st, wav_bytes()))          # altro server: ok
    await storage.add_sound(st.db, storage.GLOBAL, "Clap", upload(st, wav_bytes()))   # globale: ok


async def test_concurrent_adds_of_the_same_name_create_exactly_one(st):
    """Dashboard e comando che aggiungono lo stesso suono nello stesso istante: ne vince uno solo, nessun file orfano."""
    results = await asyncio.gather(
        *(storage.add_sound(st.db, 7, "Stesso", upload(st, wav_bytes())) for _ in range(30)),
        return_exceptions=True,
    )
    ok = [r for r in results if isinstance(r, dict)]
    assert len(ok) == 1 and sum(isinstance(r, Duplicate) for r in results) == 29
    assert files_in(storage.sounds_dir(7)) == [ok[0]["filename"]]
    assert len(await storage.list_sounds(st.db, 7)) == 1


async def test_rename_sound(st):
    a = await storage.add_sound(st.db, 7, "Uno", upload(st, wav_bytes()))
    await storage.add_sound(st.db, 7, "Due", upload(st, wav_bytes()))
    assert (await storage.rename_sound(st.db, a["id"], "  Tre  "))["name"] == "Tre"
    with pytest.raises(Duplicate):
        await storage.rename_sound(st.db, a["id"], "due")
    with pytest.raises(NotFound):
        await storage.rename_sound(st.db, 999, "x")
    with pytest.raises(NotFound):
        await storage.rename_sound(st.db, "abc", "x")
    with pytest.raises(InvalidInput):
        await storage.rename_sound(st.db, a["id"], "")
    assert (await storage.get_sound(st.db, a["id"]))["name"] == "Tre"


async def test_move_sound_between_server_and_global(st):
    row = await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    moved = await storage.move_sound(st.db, row["id"], storage.GLOBAL)
    assert moved["guild_id"] == 0
    assert files_in(storage.sounds_dir(7)) == [] and files_in(storage.sounds_dir(0)) == [row["filename"]]
    assert (await storage.move_sound(st.db, row["id"], 0))["guild_id"] == 0          # già lì: nessun effetto
    back = await storage.move_sound(st.db, row["id"], 9)
    assert back["guild_id"] == 9 and files_in(storage.sounds_dir(9)) == [row["filename"]]


async def test_move_sound_name_clash_puts_the_file_back(st):
    a = await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    await storage.add_sound(st.db, storage.GLOBAL, "clap", upload(st, wav_bytes()))
    with pytest.raises(Duplicate):
        await storage.move_sound(st.db, a["id"], storage.GLOBAL)
    assert files_in(storage.sounds_dir(7)) == [a["filename"]]           # il file è tornato al suo posto
    assert (await storage.get_sound(st.db, a["id"]))["guild_id"] == 7
    with pytest.raises(NotFound):
        await storage.move_sound(st.db, 999, 0)


async def test_move_sound_with_missing_file_is_a_clean_error(st):
    row = await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    (storage.sounds_dir(7) / row["filename"]).unlink()
    with pytest.raises(NotFound, match="disco"):
        await storage.move_sound(st.db, row["id"], 0)


async def test_delete_sound_removes_row_and_file(st):
    row = await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    await storage.delete_sound(st.db, row["id"])
    assert await storage.get_sound(st.db, row["id"]) is None and files_in(storage.sounds_dir(7)) == []
    with pytest.raises(NotFound):
        await storage.delete_sound(st.db, row["id"])


async def test_a_poisoned_filename_in_the_database_can_never_delete_outside_the_folder(st):
    secret = write(st.tmp / "data" / "secret.txt", b"x")          # data/7/soundboard/../../secret.txt
    await storage.add_sound(st.db, 7, "legittimo", upload(st, wav_bytes()))      # la cartella esiste: `..` si può attraversare
    await st.db.execute(
        "INSERT INTO sounds (guild_id, name, filename, created_at) VALUES (7, 'evil', '../../secret.txt', 0)")
    assert (storage.sounds_dir(7) / "../../secret.txt").resolve() == secret.resolve()     # il percorso punta davvero lì
    row = next(r for r in await storage.list_sounds(st.db, 7) if r["name"] == "evil")
    assert row["missing"] is True and storage.sound_file(row) is None            # non lo riconosce nemmeno
    assert await storage.resolve_sound(st.db, 7, row["id"]) is None
    await storage.delete_sound(st.db, row["id"])
    assert secret.exists()


async def test_resolve_sound_only_returns_sounds_the_guild_may_play(st):
    mine = await storage.add_sound(st.db, 7, "Mio", upload(st, wav_bytes()))
    other = await storage.add_sound(st.db, 8, "Altrui", upload(st, wav_bytes()))
    glob = await storage.add_sound(st.db, 0, "Globale", upload(st, wav_bytes()))
    ok = await storage.resolve_sound(st.db, 7, str(mine["id"]))
    assert ok and ok[1].is_file() and ok[0]["name"] == "Mio"
    assert await storage.resolve_sound(st.db, 7, other["id"]) is None             # di un altro server
    assert (await storage.resolve_sound(st.db, 7, glob["id"]))[0]["name"] == "Globale"
    for garbage in ("clap.wav", "../../etc/passwd", "-1", "0", "", "99999", "1 OR 1=1"):
        assert await storage.resolve_sound(st.db, 7, garbage) is None
    (storage.sounds_dir(7) / mine["filename"]).unlink()
    assert await storage.resolve_sound(st.db, 7, mine["id"]) is None              # file sparito


async def test_list_sounds_flags_missing_files(st):
    row = await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    assert (await storage.list_sounds(st.db, 7))[0]["missing"] is False
    (storage.sounds_dir(7) / row["filename"]).unlink()
    assert (await storage.list_sounds(st.db))[0]["missing"] is True


# -------------------------------------------------------------------------------- voci

async def test_add_voice_reads_the_wav_duration_and_rejects_global(st):
    row = await storage.add_voice(st.db, 7, "Mario", upload(st, wav_bytes(2.5)))
    assert row["duration"] == pytest.approx(2.5) and row["source_name"] == "Mario"
    assert files_in(storage.voices_dir(7)) == [row["filename"]]
    with pytest.raises(InvalidInput, match="server"):
        await storage.add_voice(st.db, storage.GLOBAL, "x", upload(st, wav_bytes()))
    with pytest.raises(Duplicate):
        await storage.add_voice(st.db, 7, "mario", upload(st, wav_bytes()))
    assert len(files_in(storage.voices_dir(7))) == 1
    mp3 = await storage.add_voice(st.db, 7, "Luigi", upload(st, MP3, "l.mp3"))
    assert mp3["duration"] is None and mp3["filename"].endswith(".mp3")


async def test_recorded_voice_is_added_then_replaced_even_after_a_rename(st):
    rec1 = write(storage.voices_dir(7) / "alice_1.wav", wav_bytes(3))
    v = await storage.save_recorded_voice(st.db, 7, "alice", "alice_1.wav", 3.0)
    assert v["name"] == "alice" and v["source_name"] == "alice"
    await storage.rename_voice(st.db, v["id"], "Alice la cantante")

    rec2 = write(storage.voices_dir(7) / "alice_2.wav", wav_bytes(4))
    again = await storage.save_recorded_voice(st.db, 7, "alice", "alice_2.wav", 4.0)
    assert again["id"] == v["id"] and again["name"] == "Alice la cantante"     # il vecchio comportamento dell'alias
    assert again["filename"] == "alice_2.wav" and not rec1.exists() and rec2.exists()
    assert len(await storage.list_voices(st.db, 7)) == 1


async def test_recorded_voice_name_clash_with_someone_elses_name_gets_a_suffix(st):
    write(storage.voices_dir(7) / "a.wav", wav_bytes())
    write(storage.voices_dir(7) / "b.wav", wav_bytes())
    first = await storage.add_voice(st.db, 7, "bob", upload(st, wav_bytes()), source_name="qualcuno")
    second = await storage.save_recorded_voice(st.db, 7, "bob", "a.wav")
    third = await storage.save_recorded_voice(st.db, 7, "bob", "b.wav")      # stesso utente di `second`: sostituisce
    assert first["name"] == "bob" and second["name"] == "bob (2)" and third["id"] == second["id"]
    with pytest.raises(NotFound):
        await storage.save_recorded_voice(st.db, 7, "ghost", "non-esiste.wav")
    with pytest.raises(NotFound):
        await storage.save_recorded_voice(st.db, 7, "ghost", "../../x.wav")


async def test_voices_are_per_server(st):
    a = await storage.add_voice(st.db, 7, "Mario", upload(st, wav_bytes()))
    await storage.add_voice(st.db, 8, "Mario", upload(st, wav_bytes()))          # stesso nome, altro server: ok
    assert [v["name"] for v in await storage.list_voices_for_guild(st.db, 7)] == ["Mario"]
    assert await storage.resolve_voice(st.db, 8, a["id"]) is None                # voce di un altro server
    ok = await storage.resolve_voice(st.db, 7, str(a["id"]))
    assert ok and ok[1].is_file()
    assert await storage.resolve_voice(st.db, 7, "../../x") is None


async def test_rename_and_delete_voice(st):
    a = await storage.add_voice(st.db, 7, "A", upload(st, wav_bytes()))
    await storage.add_voice(st.db, 7, "B", upload(st, wav_bytes()))
    assert (await storage.rename_voice(st.db, a["id"], "C"))["name"] == "C"
    with pytest.raises(Duplicate):
        await storage.rename_voice(st.db, a["id"], "b")
    with pytest.raises(NotFound):
        await storage.rename_voice(st.db, 999, "x")
    await storage.delete_voice(st.db, a["id"])
    assert files_in(storage.voices_dir(7)) != [] and len(await storage.list_voices(st.db, 7)) == 1
    with pytest.raises(NotFound):
        await storage.delete_voice(st.db, a["id"])


# --------------------------------------------------------------------------- modelli RVC

MODEL_ZIP = zip_bytes({"cartella/voce.pth": b"pesi" * 100, "cartella/voce.index": b"idx", "LEGGIMI.txt": b"ignorato"})


async def test_add_model_from_zip_extracts_only_weights_and_index(st):
    row = await storage.add_rvc_model(st.db, "Voce Uno", upload(st, MODEL_ZIP, "m.zip"), "m.zip", description="test")
    folder = storage.rvc_models_dir() / row["folder"]
    assert files_in(folder) == ["voce.index", "voce.pth"] and row["name"] == "Voce Uno"
    assert row["enabled"] is True and row["missing"] is False and row["size"] > 0
    assert not [p for p in storage.rvc_models_dir().iterdir() if p.name.startswith(".tmp")]   # niente residui


async def test_add_model_from_a_single_pth(st):
    row = await storage.add_rvc_model(st.db, "Solo Pth", upload(st, b"pesi", "mio.pth"), "mio.pth")
    assert files_in(storage.rvc_models_dir() / row["folder"]) == ["mio.pth"]
    # i .pth di PyTorch sono archivi zip: un .pth caricato da solo non va confuso con uno zip di modelli
    zipped_pth = zip_bytes({"archive/data.pkl": b"x"})
    row2 = await storage.add_rvc_model(st.db, "Pth Zip", upload(st, zipped_pth, "vero.pth"), "vero.pth")
    assert files_in(storage.rvc_models_dir() / row2["folder"]) == ["vero.pth"]


async def test_malicious_or_broken_model_zips_are_rejected_cleanly(st, monkeypatch):
    cases = {
        "nessun pth": zip_bytes({"a.index": b"x"}),
        "due pth": zip_bytes({"a.pth": b"x", "b.pth": b"x"}),
        "due index": zip_bytes({"a.pth": b"x", "a.index": b"x", "sub/b.index": b"x"}),
        "stesso nome": zip_bytes({"x/a.pth": b"1", "y/a.pth": b"2"}),
        "non è uno zip": b"questo non e' uno zip",
    }
    for label, data in cases.items():
        with pytest.raises(InvalidInput):
            await storage.add_rvc_model(st.db, f"M {label}", upload(st, data, "m.zip"), "m.zip")
    with pytest.raises(InvalidInput):
        await storage.add_rvc_model(st.db, "exe", upload(st, b"MZ", "a.exe"), "a.exe")
    monkeypatch.setattr(storage, "MAX_RVC_BYTES", 1000)
    with pytest.raises(InvalidInput, match="limite"):
        await storage.add_rvc_model(st.db, "grande", upload(st, zip_bytes({"a.pth": b"0" * 5000}), "m.zip"), "m.zip")
    assert await storage.list_rvc_models(st.db) == []
    assert files_in(storage.rvc_models_dir()) == []           # nessuna cartella rimasta


async def test_zip_slip_names_cannot_escape_the_models_folder(st):
    evil = zip_bytes({"../../evil.pth": b"x", "..\\..\\evil2.index": b"x", "/etc/cron.d/x.index": b"x"})
    with pytest.raises(InvalidInput):          # (due index: rifiutato) ma intanto nulla deve essere uscito
        await storage.add_rvc_model(st.db, "slip", upload(st, evil, "m.zip"), "m.zip")
    ok = zip_bytes({"../../evil.pth": b"x"})
    row = await storage.add_rvc_model(st.db, "slip2", upload(st, ok, "m.zip"), "m.zip")
    assert files_in(storage.rvc_models_dir() / row["folder"]) == ["evil.pth"]       # appiattito dentro la cartella
    assert not (st.tmp / "evil.pth").exists() and not (st.tmp.parent / "evil.pth").exists()


async def test_model_names_and_folders_stay_unique(st):
    a = await storage.add_rvc_model(st.db, "A B", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    b = await storage.add_rvc_model(st.db, "A_B", upload(st, MODEL_ZIP, "m.zip"), "m.zip")     # stessa cartella "A_B"
    assert a["folder"] != b["folder"]
    with pytest.raises(Duplicate):
        await storage.add_rvc_model(st.db, "a b", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    assert len(files_in(storage.rvc_models_dir())) == 2         # il tentativo fallito non lascia cartelle


async def test_model_availability_per_server_and_enabled_flag(st):
    open_model = await storage.add_rvc_model(st.db, "Aperto", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    only7 = await storage.add_rvc_model(st.db, "Solo7", upload(st, MODEL_ZIP, "m.zip"), "m.zip", guild_ids=[7])
    off = await storage.add_rvc_model(st.db, "Spento", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    await storage.update_rvc_model(st.db, off["id"], enabled=False)

    async def names(guild):
        return [m["name"] for m in await storage.list_rvc_models(st.db, guild, usable_only=True)]

    assert await names(7) == ["Aperto", "Solo7"] and await names(8) == ["Aperto"]
    assert await storage.resolve_rvc_model(st.db, 8, only7["id"]) is None
    assert await storage.resolve_rvc_model(st.db, 7, str(only7["id"])) is not None
    assert await storage.resolve_rvc_model(st.db, 7, off["id"]) is None
    assert await storage.resolve_rvc_model(st.db, 7, "../../x") is None

    updated = await storage.update_rvc_model(st.db, only7["id"], guild_ids=[], name="Per tutti", description="  d ")
    assert updated["guild_ids"] == [] and updated["name"] == "Per tutti" and updated["description"] == "d"
    assert await names(8) == ["Aperto", "Per tutti"]
    assert open_model["guild_ids"] == []


async def test_model_with_a_missing_folder_is_flagged_and_not_usable(st):
    row = await storage.add_rvc_model(st.db, "Sparito", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    import shutil
    shutil.rmtree(storage.rvc_models_dir() / row["folder"])
    assert (await storage.get_rvc_model(st.db, row["id"]))["missing"] is True
    assert await storage.resolve_rvc_model(st.db, 7, row["id"]) is None


async def test_update_and_delete_model_errors(st):
    a = await storage.add_rvc_model(st.db, "A", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    await storage.add_rvc_model(st.db, "B", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    with pytest.raises(Duplicate):
        await storage.update_rvc_model(st.db, a["id"], name="b")
    with pytest.raises(NotFound):
        await storage.update_rvc_model(st.db, 999, enabled=False)
    await storage.delete_rvc_model(st.db, a["id"])
    assert not (storage.rvc_models_dir() / a["folder"]).exists()
    with pytest.raises(NotFound):
        await storage.delete_rvc_model(st.db, a["id"])


async def test_deleting_a_model_never_touches_files_outside_the_models_folder(st):
    victim = write(st.tmp / "important" / "keep.txt", b"x")
    await st.db.execute("INSERT INTO rvc_models (name, folder, created_at) VALUES ('evil', '../important', 0)")
    row = (await storage.list_rvc_models(st.db))[0]
    assert row["missing"] is True
    await storage.delete_rvc_model(st.db, row["id"])
    assert victim.exists()


async def test_scan_registers_untracked_folders_and_reports_missing(st):
    write(storage.rvc_models_dir() / "manuale" / "x.pth", b"x")
    write(storage.rvc_models_dir() / "senza-pesi" / "leggimi.txt", b"x")
    write(storage.rvc_models_dir() / ".tmp-abc" / "x.pth", b"x")
    tracked = await storage.add_rvc_model(st.db, "Noto", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    await st.db.execute("INSERT INTO rvc_models (name, folder, created_at) VALUES ('Fantasma', 'fantasma', 0)")

    result = await storage.scan_rvc_models(st.db)
    assert result == {"added": ["manuale"], "missing": ["Fantasma"]}
    assert (await storage.scan_rvc_models(st.db))["added"] == []             # idempotente
    assert tracked["name"] in [m["name"] for m in await storage.list_rvc_models(st.db)]


# ------------------------------------------------------------------------------- server

async def test_guild_cache_sync_counts_and_orphans(st):
    await storage.sync_guilds(st.db, [(7, "Casa", "https://i/7.png", 12), (8, "Ufficio", None, 3)])
    await storage.add_sound(st.db, 7, "Clap", upload(st, wav_bytes()))
    await storage.add_voice(st.db, 7, "Mario", upload(st, wav_bytes()))
    await storage.add_sound(st.db, 99, "Orfano", upload(st, wav_bytes()))        # server non in cache (dati importati)
    guilds = {g["id"]: g for g in await storage.list_guilds(st.db)}
    assert guilds[7]["name"] == "Casa" and (guilds[7]["sounds"], guilds[7]["voices"]) == (1, 1)
    assert guilds[8]["sounds"] == 0 and guilds[99]["name"] == "Server 99" and guilds[99]["present"] == 0

    await storage.sync_guilds(st.db, [(7, "Casa Nuova", None, 13)])               # il bot è uscito dal server 8
    await storage.mark_guild_left(st.db, 7)
    guilds = {g["id"]: g for g in await storage.list_guilds(st.db)}
    assert guilds[7]["name"] == "Casa Nuova" and guilds[7]["present"] == 0 and guilds[8]["present"] == 0


async def test_overview_counts(st):
    await storage.sync_guilds(st.db, [(7, "Casa", None, 1)])
    await storage.add_sound(st.db, 7, "A", upload(st, wav_bytes()))
    await storage.add_sound(st.db, 0, "B", upload(st, wav_bytes()))
    await storage.add_voice(st.db, 7, "V", upload(st, wav_bytes()))
    await storage.add_rvc_model(st.db, "M", upload(st, MODEL_ZIP, "m.zip"), "m.zip")
    data = await storage.overview(st.db)
    assert (data["guilds"], data["sounds"], data["global_sounds"], data["voices"], data["rvc_models"]) == (1, 1, 1, 1, 1)
    assert data["disk_bytes"] > 0


async def test_unique_violation_helper_only_matches_unique_errors():
    assert storage._is_unique_violation(sqlite3.IntegrityError("UNIQUE constraint failed: sounds.name"))
    assert not storage._is_unique_violation(sqlite3.IntegrityError("FOREIGN KEY constraint failed"))
