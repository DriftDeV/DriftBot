"""Test del livello SQLite: scritture concorrenti, coda, WAL, migrazioni, più processi."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import database
from database import Database, DatabaseBusy, DatabaseClosed, DatabaseError

SRC = Path(database.__file__).parent


@pytest.fixture
def db(tmp_path):
    database_ = Database(tmp_path / "bot.sqlite3").start()
    yield database_
    database_.close()


def insert_sound(conn, name, guild_id=0):
    return conn.execute(
        "INSERT INTO sounds (guild_id, name, filename, created_at) VALUES (?, ?, ?, 0)",
        (guild_id, name, f"{name}.wav"),
    ).lastrowid


def count(db, table="sounds"):
    return db.read_sync(lambda c: c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class Gate:
    """Tiene occupato il thread scrittore finché non viene aperta, così le scritture si accumulano in coda."""

    def __init__(self, db):
        self.started, self.release = threading.Event(), threading.Event()

        def block(conn):
            self.started.set()
            self.release.wait(10)

        self.future = db._enqueue(block)
        assert self.started.wait(5)

    def open(self):
        self.release.set()
        self.future.result(5)


# --------------------------------------------------------------------------- schema

def test_schema_is_created_with_wal_and_version(db):
    tables = {r[0] for r in db.read_sync(lambda c: c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())}
    assert {"meta", "guilds", "sounds", "voices", "rvc_models", "rvc_model_access", "audit_log"} <= tables
    assert db.read_sync(lambda c: c.execute("PRAGMA user_version").fetchone()[0]) == database.SCHEMA_VERSION
    assert db.stats()["journal_mode"] == "wal"


def test_reopening_is_idempotent_and_keeps_data(tmp_path):
    first = Database(tmp_path / "x.sqlite3").start()
    first.write_sync(insert_sound, "clap")
    first.close()
    second = Database(tmp_path / "x.sqlite3").start()
    assert count(second) == 1
    second.close()


def test_database_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "new.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 5}")
    conn.close()
    with pytest.raises(DatabaseError, match="più recente"):
        Database(path).start()


def test_names_are_unique_case_insensitively_per_scope(db):
    db.write_sync(insert_sound, "Clap", 1)
    db.write_sync(insert_sound, "Clap", 2)          # altro server: va bene
    db.write_sync(insert_sound, "Clap", 0)          # globale: va bene
    with pytest.raises(sqlite3.IntegrityError):
        db.write_sync(insert_sound, "clap", 1)


def test_deleting_a_model_removes_its_access_rows(db):
    def setup(conn):
        mid = conn.execute("INSERT INTO rvc_models (name, folder, created_at) VALUES ('a','a',0)").lastrowid
        conn.execute("INSERT INTO rvc_model_access VALUES (?, 5)", (mid,))
        return mid

    mid = db.write_sync(setup)
    db.write_sync(lambda c: c.execute("DELETE FROM rvc_models WHERE id=?", (mid,)))
    assert count(db, "rvc_model_access") == 0


# --------------------------------------------------------------- scritture concorrenti

async def test_many_concurrent_async_writers_all_commit(db):
    """Il caso del problema: tante richieste (comandi + dashboard) scrivono nello stesso istante."""
    await asyncio.gather(*(db.write(insert_sound, f"s{i}", i % 7) for i in range(400)))
    assert count(db) == 400
    stats = db.stats()
    assert stats["writes_done"] == 400 and stats["writes_failed"] == 0


def test_many_threads_writing_at_once_never_hit_database_locked(db):
    errors = []

    def worker(n):
        try:
            for i in range(40):
                db.write_sync(insert_sound, f"t{n}-{i}", n)
        except Exception as e:      # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == [] and count(db) == 480


def test_queued_writes_are_batched_into_one_transaction(db):
    gate = Gate(db)
    futures = [db._enqueue(lambda c, i=i: insert_sound(c, f"b{i}")) for i in range(50)]
    before = db.stats()["batches"]
    gate.open()
    for f in futures:
        f.result(5)
    stats = db.stats()
    assert stats["max_batch"] >= 20 and stats["batches"] - before <= 3     # molte scritture, pochi commit
    assert count(db) == 50


def test_writes_run_in_order(db):
    gate = Gate(db)
    order = []
    futures = [db._enqueue(lambda c, i=i: order.append(i)) for i in range(30)]
    gate.open()
    for f in futures:
        f.result(5)
    assert order == list(range(30))


def test_a_failing_write_is_rolled_back_alone_and_its_neighbours_commit(db):
    gate = Gate(db)
    good_before = db._enqueue(lambda c: insert_sound(c, "ok1"))

    def half_done_then_error(conn):
        insert_sound(conn, "meta-a")
        insert_sound(conn, "meta-b")
        raise ValueError("boom")

    bad = db._enqueue(half_done_then_error)
    duplicate = db._enqueue(lambda c: insert_sound(c, "ok1"))        # UNIQUE violata
    good_after = db._enqueue(lambda c: insert_sound(c, "ok2"))
    gate.open()

    good_before.result(5), good_after.result(5)
    with pytest.raises(ValueError):
        bad.result(5)
    with pytest.raises(sqlite3.IntegrityError):
        duplicate.result(5)
    names = sorted(r[0] for r in db.read_sync(lambda c: c.execute("SELECT name FROM sounds").fetchall()))
    assert names == ["ok1", "ok2"]          # nessuna modifica "a metà" di `bad`
    assert db.stats()["writes_failed"] == 2


async def test_integrity_errors_reach_the_awaiting_caller(db):
    await db.write(insert_sound, "x", 1)
    with pytest.raises(sqlite3.IntegrityError):
        await db.write(insert_sound, "X", 1)
    assert await db.write(insert_sound, "y", 1)        # la coda continua a funzionare


def test_a_write_that_kills_the_transaction_fails_the_batch_but_not_the_database(db):
    gate = Gate(db)
    innocent = db._enqueue(lambda c: insert_sound(c, "innocente"))

    def sabotage(conn):
        conn.execute("ROLLBACK")             # simula un errore che annulla l'intera transazione (disco pieno...)
        raise RuntimeError("transazione persa")

    bad = db._enqueue(sabotage)
    gate.open()
    with pytest.raises(RuntimeError):
        bad.result(5)
    with pytest.raises(RuntimeError):
        innocent.result(5)                   # non è stata scritta davvero: non può risultare riuscita
    assert count(db) == 0
    assert db.write_sync(insert_sound, "dopo") and count(db) == 1       # il database è ancora sano


def test_cancelled_writes_are_skipped(db):
    gate = Gate(db)
    ran = []
    victim = db._enqueue(lambda c: ran.append("victim"))
    survivor = db._enqueue(lambda c: ran.append("survivor"))
    assert victim.cancel()
    gate.open()
    survivor.result(5)
    assert ran == ["survivor"]


def test_write_sync_inside_the_writer_thread_is_refused_instead_of_deadlocking(db):
    def nested(conn):
        db.write_sync(insert_sound, "x")

    with pytest.raises(DatabaseError, match="deadlock"):
        db.write_sync(nested)


# ----------------------------------------------------------------------------- letture

def test_reads_do_not_wait_for_a_long_running_write(db):
    db.write_sync(insert_sound, "esistente")
    gate = Gate(db)                           # il writer è occupato (e dentro una transazione aperta)
    start = time.monotonic()
    assert count(db) == 1
    assert time.monotonic() - start < 1
    gate.open()


def test_readers_never_see_a_half_committed_batch(db):
    gate_in_tx, finish = threading.Event(), threading.Event()

    def long_insert(conn):
        insert_sound(conn, "nuovo")
        gate_in_tx.set()
        finish.wait(5)

    future = db._enqueue(long_insert)
    assert gate_in_tx.wait(5)
    assert count(db) == 0                     # non ancora committato: invisibile
    finish.set()
    future.result(5)
    assert count(db) == 1


async def test_async_fetch_helpers(db):
    await db.write(insert_sound, "uno", 3)
    assert [r["name"] for r in await db.fetchall("SELECT name FROM sounds WHERE guild_id=?", (3,))] == ["uno"]
    assert (await db.fetchone("SELECT name FROM sounds WHERE guild_id=?", (3,)))["name"] == "uno"
    assert await db.fetchone("SELECT * FROM sounds WHERE guild_id=?", (99,)) is None
    result = await db.execute("UPDATE sounds SET size=5 WHERE guild_id=3")
    assert result.rowcount == 1


def test_reader_connections_cannot_write(db):
    with pytest.raises(sqlite3.OperationalError):
        db.read_sync(lambda c: c.execute("INSERT INTO meta VALUES ('a','b')"))


# ------------------------------------------------------------------------ più processi

CHILD = textwrap.dedent("""
    import sys
    sys.path.insert(0, {src!r})
    from database import Database
    db = Database({path!r}).start()
    n = int(sys.argv[1])
    for i in range(60):
        db.write_sync(lambda c, i=i: c.execute(
            "INSERT INTO sounds (guild_id, name, filename, created_at) VALUES (?, ?, 'f', 0)",
            (n, "p%d-%d" % (n, i))))
    db.close()
""")


def test_separate_processes_writing_to_the_same_file(tmp_path):
    """Bot e dashboard in due processi: ognuno ha la sua coda, il file lo arbitra SQLite."""
    path = tmp_path / "shared.sqlite3"
    Database(path).start().close()
    code = CHILD.format(src=str(SRC), path=str(path))
    procs = [subprocess.Popen([sys.executable, "-c", code, str(n)], stderr=subprocess.PIPE, text=True) for n in range(5)]

    parent = Database(path).start()           # e intanto scrive anche il processo "bot"
    for i in range(60):
        parent.write_sync(insert_sound, f"parent-{i}", 99)

    for proc in procs:
        _, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
    assert count(parent) == 60 + 5 * 60
    parent.close()


def test_a_write_waits_for_an_external_lock_and_then_succeeds(tmp_path):
    path = tmp_path / "locked.sqlite3"
    db = Database(path, busy_timeout_ms=3000).start()
    other = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")           # un altro processo tiene il lock di scrittura

    threading.Timer(0.5, lambda: other.execute("COMMIT")).start()
    start = time.monotonic()
    db.write_sync(insert_sound, "dopo-il-lock")
    assert 0.3 < time.monotonic() - start < 3
    assert count(db) == 1
    other.close()
    db.close()


def test_a_lock_held_too_long_becomes_database_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "BEGIN_RETRIES", 1)
    path = tmp_path / "stuck.sqlite3"
    db = Database(path, busy_timeout_ms=50).start()
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    with pytest.raises(DatabaseBusy):
        db.write_sync(insert_sound, "mai")
    other.execute("ROLLBACK")
    assert db.write_sync(insert_sound, "ora-si")        # sbloccato: tutto torna a funzionare
    other.close()
    db.close()


# ------------------------------------------------------------------------- chiusura

def test_close_flushes_everything_still_queued(tmp_path):
    path = tmp_path / "close.sqlite3"
    db = Database(path).start()
    gate = Gate(db)
    futures = [db._enqueue(lambda c, i=i: insert_sound(c, f"q{i}")) for i in range(100)]
    closer = threading.Thread(target=db.close)
    closer.start()
    time.sleep(0.1)
    gate.open()
    closer.join(10)
    assert all(f.result(5) for f in futures)
    check = sqlite3.connect(path)
    assert check.execute("SELECT COUNT(*) FROM sounds").fetchone()[0] == 100
    check.close()


async def test_closed_database_refuses_work_and_close_is_idempotent(tmp_path):
    db = await Database.open(tmp_path / "c.sqlite3")
    await db.aclose()
    await db.aclose()
    with pytest.raises(DatabaseClosed):
        await db.write(insert_sound, "x")
    with pytest.raises(DatabaseClosed):
        await db.fetchall("SELECT 1")


def test_write_before_start_is_a_clear_error(tmp_path):
    with pytest.raises(DatabaseError, match="start"):
        Database(tmp_path / "n.sqlite3").write_sync(insert_sound, "x")


def test_wal_checkpoint_on_close_leaves_a_single_file(tmp_path):
    path = tmp_path / "wal.sqlite3"
    db = Database(path).start()
    db.write_sync(insert_sound, "x")
    db.close()
    assert not Path(str(path) + "-wal").exists() or Path(str(path) + "-wal").stat().st_size == 0
    assert os.path.getsize(path) > 0
