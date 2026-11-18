"""Autenticazione della dashboard: password, sessioni in memoria, token CSRF e limite ai tentativi di login."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Optional

MAX_SESSIONS = 50


@dataclass
class Session:
    token: str
    csrf: str
    expires: float


class SessionStore:
    """Sessioni solo in memoria: un riavvio del bot/della dashboard richiede un nuovo login (voluto)."""

    def __init__(self, ttl: float, clock=time.monotonic):
        self.ttl = ttl
        self._clock = clock
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        self._purge()
        while len(self._sessions) >= MAX_SESSIONS:       # tetto alle sessioni: via la più vecchia
            oldest = min(self._sessions.values(), key=lambda s: s.expires)
            del self._sessions[oldest.token]
        session = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), self._clock() + self.ttl)
        self._sessions[session.token] = session
        return session

    def get(self, token: Optional[str]) -> Optional[Session]:
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires <= self._clock():
            del self._sessions[token]
            return None
        return session

    def delete(self, token: Optional[str]) -> None:
        if token:
            self._sessions.pop(token, None)

    def _purge(self) -> None:
        now = self._clock()
        for token in [t for t, s in self._sessions.items() if s.expires <= now]:
            del self._sessions[token]

    def __len__(self) -> int:
        return len(self._sessions)


class LoginLimiter:
    """Dopo `max_failures` password sbagliate dallo stesso indirizzo, blocca i tentativi per `lockout` secondi."""

    def __init__(self, max_failures: int = 5, window: float = 300, lockout: float = 300, clock=time.monotonic):
        self.max_failures, self.window, self.lockout = max_failures, window, lockout
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}

    def retry_after(self, ip: str) -> float:
        """Secondi di attesa residui (0 se può provare)."""
        until = self._blocked_until.get(ip, 0)
        remaining = until - self._clock()
        if remaining <= 0:
            self._blocked_until.pop(ip, None)
            return 0
        return remaining

    def failure(self, ip: str) -> None:
        now = self._clock()
        recent = [t for t in self._failures.get(ip, []) if now - t < self.window]
        recent.append(now)
        self._failures[ip] = recent
        if len(recent) >= self.max_failures:
            self._blocked_until[ip] = now + self.lockout
            self._failures.pop(ip, None)
        if len(self._failures) > 1000:                   # non crescere all'infinito sotto attacco
            self._failures.clear()

    def success(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._blocked_until.pop(ip, None)


def password_matches(expected: str, given: object) -> bool:
    """Confronto a tempo costante (nessuna informazione dai tempi di risposta)."""
    if not isinstance(given, str):
        return False
    return hmac.compare_digest(expected.encode("utf-8"), given.encode("utf-8"))


def tokens_match(expected: str, given: Optional[str]) -> bool:
    return bool(given) and hmac.compare_digest(expected.encode("ascii", "ignore"), (given or "").encode("ascii", "ignore"))
