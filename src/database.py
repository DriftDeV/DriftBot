"""
Database SQLite del bot, pensato per le scritture contemporanee.

Il problema: SQLite ammette UN SOLO scrittore alla volta. Il bot (slash command), la dashboard
(richieste HTTP) e i worker in background vogliono scrivere nello stesso momento.

La soluzione, in tre pezzi:

1. **Coda di scrittura + thread scrittore unico.** Ogni scrittura è una funzione messa in coda
   (`Database.write`); un solo thread le esegue una dopo l'altra, raggruppandole in un'unica
   transazione (`BEGIN IMMEDIATE ... COMMIT`) quando ne arrivano molte insieme. Così dentro
   un processo le scritture non si contendono mai il lock e un picco di richieste costa un solo
   fsync. Ogni scrittura gira in un SAVEPOINT: se una fallisce (es. nome duplicato) viene annullata
   da sola, senza trascinare con sé le altre del gruppo.
2. **WAL + connessioni di sola lettura.** In modalità WAL chi legge non blocca chi scrive (e viceversa):
   le letture (autocomplete, liste della dashboard) passano da un piccolo pool di connessioni
   `query_only` e non attendono mai la coda di scrittura.
3. **`busy_timeout` + retry per i processi multipli.** Se la dashboard gira in un processo separato
   dal bot, i due processi hanno ciascuno la propria coda; il file viene arbitrato da SQLite
   (`BEGIN IMMEDIATE` attende fino a `busy_timeout` e, se serve, si riprova).

Le funzioni passate a `write` ricevono la connessione e NON devono fare commit/rollback né
usare `await`: girano nel thread scrittore.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import sqlite3
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_BUSY_TIMEOUT_MS = 10_000
DEFAULT_MAX_BATCH = 64
DEFAULT_READERS = 4
BEGIN_RETRIES = 5            # tentativi di BEGIN IMMEDIATE oltre al busy_timeout di SQLite


class DatabaseError(Exception):
    """Errore del database (messaggio adatto ai log, non all'utente finale)."""


class DatabaseClosed(DatabaseError):
    """Il database è stato chiuso: nessuna nuova scrittura/lettura."""


class DatabaseBusy(DatabaseError):
    """Il file è rimasto bloccato (da un altro processo) più a lungo del busy_timeout."""


# ----------------------------------------------------------------------------- schema

# Una lista di istruzioni per ogni versione. La versione corrente è PRAGMA user_version.
# Non si modificano mai le migrazioni già rilasciate: se ne aggiunge una nuova in fondo.
MIGRATIONS: list[list[str]] = [
    # --- v1 -------------------------------------------------------------------
    [
        """CREATE TABLE meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        # Cache dei server: la scrive il bot, così la dashboard (anche in un altro processo)
        # mostra i nomi senza dover essere connessa a Discord.
        """CREATE TABLE guilds (
            id           INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            icon_url     TEXT,
            member_count INTEGER,
            present      INTEGER NOT NULL DEFAULT 1,
            updated_at   REAL NOT NULL
        )""",
        # guild_id = 0 -> soundboard GLOBALE (disponibile in tutti i server)
        """CREATE TABLE sounds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   INTEGER NOT NULL DEFAULT 0,
            name       TEXT NOT NULL COLLATE NOCASE,
            filename   TEXT NOT NULL,
            size       INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE (guild_id, name)
        )""",
        "CREATE INDEX idx_sounds_guild ON sounds (guild_id)",
        # Voci clonate (speaker): una per utente registrato, per server.
        # `source_name` è il nome Discord con cui è stata registrata: serve a sostituire la voce
        # (e non duplicarla) se la stessa persona viene registrata di nuovo dopo un rename.
        """CREATE TABLE voices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            name        TEXT NOT NULL COLLATE NOCASE,
            source_name TEXT,
            filename    TEXT NOT NULL,
            duration    REAL,
            size        INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL,
            UNIQUE (guild_id, name)
        )""",
        "CREATE INDEX idx_voices_guild ON voices (guild_id)",
        # Modelli RVC: i file stanno in RVC/models/<folder>. Senza righe in rvc_model_access il
        # modello è disponibile in tutti i server; con almeno una riga solo nei server elencati.
        """CREATE TABLE rvc_models (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL COLLATE NOCASE UNIQUE,
            folder      TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            enabled     INTEGER NOT NULL DEFAULT 1,
            size        INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL
        )""",
        """CREATE TABLE rvc_model_access (
            model_id INTEGER NOT NULL REFERENCES rvc_models (id) ON DELETE CASCADE,
            guild_id INTEGER NOT NULL,
            PRIMARY KEY (model_id, guild_id)
        )""",
        # Registro delle modifiche fatte dalla dashboard (chi, cosa, quando)
        """CREATE TABLE audit_log (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            ts     REAL NOT NULL,
            actor  TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )""",
        "CREATE INDEX idx_audit_ts ON audit_log (ts)",
    ],
]

SCHEMA_VERSION = len(MIGRATIONS)


def _is_locked_error(error: BaseException) -> bool:
    text = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and ("locked" in text or "busy" in text)


def migrate(conn: sqlite3.Connection) -> int:
    """
    Porta lo schema all'ultima versione. Sicuro con più processi che partono insieme: la versione
    si legge DOPO aver ottenuto il lock di scrittura, quindi solo uno applica le migrazioni.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise DatabaseError(
                f"Il database è alla versione {version}, più recente di quella supportata "
                f"({SCHEMA_VERSION}): aggiorna il bot."
            )
        for target in range(version, SCHEMA_VERSION):
            for statement in MIGRATIONS[target]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target + 1}")
            log.info("Database migrato alla versione %d", target + 1)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return SCHEMA_VERSION


# --------------------------------------------------------------------------- database

class _Job:
    __slots__ = ("fn", "future")

    def __init__(self, fn: Callable[[sqlite3.Connection], Any], future: Future):
        self.fn = fn
        self.future = future


_STOP = object()


class Database:
    """
    Wrapper SQLite con coda di scrittura. Uso tipico:

        db = Database(path); db.start()
        new_id = await db.write(lambda c: c.execute("INSERT ...", (...)).lastrowid)
        rows = await db.fetchall("SELECT ...", (...))
        await db.aclose()
    """

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        max_batch: int = DEFAULT_MAX_BATCH,
        readers: int = DEFAULT_READERS,
    ):
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self.max_batch = max(1, max_batch)
        self._reader_count = max(1, readers)

        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._lock = threading.Lock()           # protegge _closed e l'ordine di accodamento
        self._closed = False
        self._started = False
        self._ready = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._writer: Optional[threading.Thread] = None
        self._readers: "queue.LifoQueue[sqlite3.Connection]" = queue.LifoQueue()
        self._reader_conns: list[sqlite3.Connection] = []

        # statistiche per la dashboard
        self._stats_lock = threading.Lock()
        self._writes_done = 0
        self._writes_failed = 0
        self._batches = 0
        self._max_batch_seen = 0
        self._last_error: Optional[str] = None
        self._journal_mode = "?"

    # ------------------------------------------------------------ connessioni

    def _connect(self, *, read_only: bool) -> sqlite3.Connection:
        # isolation_level=None: le transazioni le gestiamo noi (BEGIN/SAVEPOINT espliciti)
        conn = sqlite3.connect(
            str(self.path),
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys = ON")
        if read_only:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def _configure_writer(self, conn: sqlite3.Connection) -> None:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        self._journal_mode = str(mode).lower()
        if self._journal_mode != "wal":
            # Succede su alcuni file system di rete: funziona lo stesso, ma letture e scritture si bloccano a vicenda
            log.warning("WAL non disponibile (journal_mode=%s): le letture potrebbero attendere le scritture", mode)
        conn.execute("PRAGMA synchronous = NORMAL")   # sicuro in WAL: al massimo si perde l'ultimo commit se salta la corrente

    # ----------------------------------------------------------------- avvio

    def start(self) -> "Database":
        """Apre il file, applica le migrazioni e avvia il thread scrittore. Idempotente."""
        with self._lock:
            if self._closed:
                raise DatabaseClosed("Database chiuso")
            if self._started:
                return self
            self._started = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = threading.Thread(target=self._writer_loop, name="sqlite-writer", daemon=True)
        self._writer.start()
        self._ready.wait()
        if self._start_error is not None:
            error = self._start_error
            with self._lock:
                self._closed = True
            if self._writer is not None:
                self._writer.join(timeout=5)
            raise error
        for _ in range(self._reader_count):
            conn = self._connect(read_only=True)
            self._reader_conns.append(conn)
            self._readers.put(conn)
        return self

    @classmethod
    async def open(cls, path: str | Path, **kwargs: Any) -> "Database":
        db = cls(path, **kwargs)
        await asyncio.to_thread(db.start)
        return db

    # ------------------------------------------------------- thread scrittore

    def _writer_loop(self) -> None:
        try:
            conn = self._connect(read_only=False)
            self._configure_writer(conn)
            self._with_begin_retry(lambda: migrate(conn))
        except BaseException as e:   # noqa: BLE001 - l'errore viene rilanciato da start()
            self._start_error = e
            self._ready.set()
            return
        self._ready.set()

        stopping = False
        try:
            while not stopping:
                first = self._queue.get()
                if first is _STOP:
                    break
                batch = [first]
                while len(batch) < self.max_batch:
                    try:
                        nxt = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if nxt is _STOP:
                        stopping = True
                        break
                    batch.append(nxt)
                self._run_batch(conn, batch)
        finally:
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            conn.close()

    @staticmethod
    def _with_begin_retry(fn: Callable[[], T]) -> T:
        """Riprova se il file è bloccato da un altro processo (oltre al busy_timeout di SQLite)."""
        delay = 0.05
        for attempt in range(BEGIN_RETRIES + 1):
            try:
                return fn()
            except sqlite3.OperationalError as e:
                if not _is_locked_error(e):
                    raise
                if attempt == BEGIN_RETRIES:
                    raise DatabaseBusy("Database bloccato da un altro processo") from e
                log.warning("Database occupato, riprovo tra %.2fs (tentativo %d)", delay, attempt + 1)
                time.sleep(delay)
                delay = min(delay * 2, 1.0)
        raise AssertionError("unreachable")  # pragma: no cover

    def _run_batch(self, conn: sqlite3.Connection, batch: list[_Job]) -> None:
        # Le scritture già annullate (future cancellati) non vengono eseguite
        jobs = [job for job in batch if job.future.set_running_or_notify_cancel()]
        if not jobs:
            return

        def begin() -> None:
            conn.execute("BEGIN IMMEDIATE")

        try:
            self._with_begin_retry(begin)
        except BaseException as e:   # noqa: BLE001
            self._fail_all(jobs, e)
            return

        outcomes: list[tuple[_Job, bool, Any]] = []
        for job in jobs:
            conn.execute("SAVEPOINT job")
            try:
                result = job.fn(conn)
            except BaseException as e:   # noqa: BLE001 - qualunque errore annulla SOLO questa scrittura
                try:
                    conn.execute("ROLLBACK TO job")
                    conn.execute("RELEASE job")
                except sqlite3.Error:
                    # SQLite ha annullato da solo l'intera transazione (disco pieno, I/O error...):
                    # le scritture precedenti del gruppo non esistono più, quindi falliscono tutte.
                    self._abort_transaction(conn)
                    self._fail_all(jobs, e)
                    return
                outcomes.append((job, False, e))
            else:
                conn.execute("RELEASE job")
                outcomes.append((job, True, result))

        try:
            conn.execute("COMMIT")
        except BaseException as e:   # noqa: BLE001 - nulla è stato scritto davvero: falliscono tutte
            self._abort_transaction(conn)
            self._fail_all(jobs, e)
            return

        failed = 0
        for job, ok, value in outcomes:
            if ok:
                job.future.set_result(value)
            else:
                failed += 1
                job.future.set_exception(value)
        with self._stats_lock:
            self._batches += 1
            self._writes_done += len(outcomes) - failed
            self._writes_failed += failed
            self._max_batch_seen = max(self._max_batch_seen, len(outcomes))

    @staticmethod
    def _abort_transaction(conn: sqlite3.Connection) -> None:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    def _fail_all(self, jobs: Iterable[_Job], error: BaseException) -> None:
        jobs = list(jobs)
        log.error("Scrittura SQLite fallita (%d operazioni): %s", len(jobs), error)
        with self._stats_lock:
            self._writes_failed += len(jobs)
            self._last_error = str(error)
        for job in jobs:
            job.future.set_exception(error)

    # ----------------------------------------------------------------- scritture

    def _enqueue(self, fn: Callable[[sqlite3.Connection], Any]) -> Future:
        future: Future = Future()
        with self._lock:
            if self._closed:
                raise DatabaseClosed("Database chiuso")
            if not self._started:
                raise DatabaseError("Database non avviato: chiama start()")
            self._queue.put(_Job(fn, future))
        return future

    async def write(self, fn: Callable[..., T], *args: Any) -> T:
        """
        Esegue `fn(conn, *args)` nel thread scrittore e attende il commit.
        Se `fn` solleva un'eccezione viene rilanciata qui e le sue modifiche sono annullate.
        """
        future = self._enqueue(lambda conn: fn(conn, *args))
        return await asyncio.wrap_future(future)

    def write_sync(self, fn: Callable[..., T], *args: Any, timeout: Optional[float] = None) -> T:
        """Come `write`, ma bloccante (script, test, thread che non sono nell'event loop)."""
        if threading.current_thread() is self._writer:
            raise DatabaseError("write_sync dentro il thread scrittore: deadlock")
        future = self._enqueue(lambda conn: fn(conn, *args))
        return future.result(timeout)

    async def execute(self, sql: str, params: Sequence[Any] | dict = ()) -> "WriteResult":
        """Singola istruzione di scrittura. Restituisce un oggetto con `lastrowid` e `rowcount`."""

        def run(conn: sqlite3.Connection) -> "WriteResult":
            cur = conn.execute(sql, params)
            return WriteResult(cur.lastrowid, cur.rowcount)

        return await self.write(run)

    # ------------------------------------------------------------------- letture

    def _read(self, fn: Callable[..., T], args: tuple) -> T:
        if self._closed:
            raise DatabaseClosed("Database chiuso")
        conn = self._readers.get()
        try:
            # Una transazione di sola lettura: più query dentro `fn` vedono lo stesso snapshot
            conn.execute("BEGIN")
            try:
                return fn(conn, *args)
            finally:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
        finally:
            self._readers.put(conn)

    async def read(self, fn: Callable[..., T], *args: Any) -> T:
        """Esegue `fn(conn, *args)` su una connessione di sola lettura, in un thread."""
        return await asyncio.to_thread(self._read, fn, args)

    def read_sync(self, fn: Callable[..., T], *args: Any) -> T:
        return self._read(fn, args)

    async def fetchall(self, sql: str, params: Sequence[Any] | dict = ()) -> list[dict]:
        return await self.read(lambda c: [dict(r) for r in c.execute(sql, params).fetchall()])

    async def fetchone(self, sql: str, params: Sequence[Any] | dict = ()) -> Optional[dict]:
        def run(conn: sqlite3.Connection) -> Optional[dict]:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

        return await self.read(run)

    # --------------------------------------------------------------------- stato

    def stats(self) -> dict:
        size = _file_size(self.path)
        with self._stats_lock:
            return {
                "path": str(self.path),
                "journal_mode": self._journal_mode,
                "schema_version": SCHEMA_VERSION,
                "size_bytes": size,
                "wal_bytes": _file_size(Path(str(self.path) + "-wal")),
                "queue_depth": self._queue.qsize(),
                "writes_done": self._writes_done,
                "writes_failed": self._writes_failed,
                "batches": self._batches,
                "max_batch": self._max_batch_seen,
                "last_error": self._last_error,
            }

    # --------------------------------------------------------------- chiusura

    def close(self) -> None:
        """Esegue le scritture ancora in coda, poi chiude tutto. Idempotente."""
        with self._lock:
            already = self._closed
            self._closed = True
            if not already and self._started and self._writer is not None:
                self._queue.put(_STOP)   # dopo tutto ciò che è già in coda: niente scritture perse
        if self._writer is not None and self._writer is not threading.current_thread():
            self._writer.join()
        for conn in self._reader_conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._reader_conns.clear()

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)


class WriteResult:
    """Esito di `Database.execute`: l'id dell'ultima riga inserita e le righe toccate."""

    __slots__ = ("lastrowid", "rowcount")

    def __init__(self, lastrowid: Optional[int], rowcount: int):
        self.lastrowid = lastrowid
        self.rowcount = rowcount


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
