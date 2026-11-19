"""Finti server HTTP per i test: ACE-Step 1.5 (contratto documentato) e Ollama."""

import json

from aiohttp import web

AUDIO = b"ID3" + b"\x01" * 2000

def envelope(data, code=200, error=None):
    return web.json_response({"data": data, "code": code, "error": error, "timestamp": 1, "extra": None})


class FakeAceStep:
    """Server ACE-Step finto. Le proprietà pubbliche regolano il comportamento."""

    def __init__(self, log=None):
        self.log = log if log is not None else []   # eventi condivisi con FakeOllama (per verificare l'ordine)
        self.api_key = ""              # se valorizzata, richiede Authorization: Bearer
        self.running_polls = 0         # quante volte /query_result risponde "in corso" prima del successo
        self.final_status = 1          # stato finale del task: 1 ok, 2 fallito
        self.item_failed = False       # task ok ma brano interno fallito
        self.never_finish = False
        self.gate = None               # asyncio.Event: finché non è impostato il task resta in corso
        self.forget_tasks = False
        self.release_http = 200
        self.release_code = 200
        self.bad_json = False
        self.file_ref = "/v1/audio?path=%2Ftmp%2Fapi_audio%2Fabc.mp3"
        self.audio = AUDIO
        self.chunked = False
        self.queue_position = 1
        self.submitted = []
        self.polls = 0
        self.downloads = 0
        self.headers_seen = []
        self.healthy = True            # False: /health risponde 503 (server ancora in avvio)

    def app(self):
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_post("/release_task", self.release_task)
        app.router.add_post("/query_result", self.query_result)
        app.router.add_get("/v1/audio", self.get_audio)
        return app

    def _auth_ok(self, request):
        self.headers_seen.append(dict(request.headers))
        return not self.api_key or request.headers.get("Authorization") == f"Bearer {self.api_key}"

    async def health(self, request):
        if not self.healthy:
            return web.json_response({"detail": "loading"}, status=503)
        return envelope({"status": "ok"})

    async def release_task(self, request):
        if not self._auth_ok(request):
            return web.json_response({"detail": "Unauthorized"}, status=401)
        if self.release_http != 200:
            return web.json_response({"detail": "x"}, status=self.release_http)
        if self.bad_json:
            return web.Response(text="<html>non json</html>", content_type="text/html")
        body = await request.json()
        self.submitted.append(body)
        self.log.append("ace_release")
        if self.release_code != 200:
            return envelope(None, code=self.release_code, error="Qualcosa è andato storto /home/segreto")
        return envelope({"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "queued",
                         "queue_position": self.queue_position})

    async def query_result(self, request):
        if not self._auth_ok(request):
            return web.json_response({"detail": "Unauthorized"}, status=401)
        body = await request.json()
        task_id = body["task_id_list"][0]
        self.polls += 1
        if self.forget_tasks:
            return envelope([])
        waiting = self.never_finish or (self.gate is not None and not self.gate.is_set()) \
            or self.polls <= self.running_polls
        if waiting:
            return envelope([{"task_id": task_id, "status": 0, "result": "[]"}])
        if self.final_status == 2:
            return envelope([{"task_id": task_id, "status": 2, "result": "[]"}])
        self.log.append("ace_done")
        inner = {"file": self.file_ref, "status": 2 if self.item_failed else 1,
                 "metas": {"bpm": 120, "duration": 30, "keyscale": "C major"}, "seed_value": "1"}
        return envelope([{"task_id": task_id, "status": 1, "result": json.dumps([inner])}])

    async def get_audio(self, request):
        self.downloads += 1
        self.log.append("ace_download")
        if self.chunked:
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(self.audio)
            await response.write_eof()
            return response
        return web.Response(body=self.audio, content_type="audio/mpeg")


class FakeOllama:
    """
    Ollama finto: /api/chat (con keep_alive e unload esplicito con messages=[]) e /api/ps.
    Gli eventi vanno nello stesso log di FakeAceStep, così si verifica l'ordine delle operazioni.
    """

    GOOD = (
        "[verse]\nLuci di città che si accendono\nPasso lento sotto la pioggia\n"
        "[chorus]\nCanto con te fino a domani\nLa notte è nostra, resta qui"
    )

    def __init__(self, log=None, model="qwen2.5:7b"):
        self.log = log if log is not None else []
        self.model = model
        self.content = self.GOOD
        self.chat_status = 200
        self.delay = 0.0
        self.gate = None               # asyncio.Event: la chat resta in attesa finché non è impostato
        self.linger_polls = 0          # /api/ps continua a dire "caricato" per N richieste dopo la chat
        self.sticky = False            # ignora keep_alive:0 (resta in memoria finché non c'è un unload esplicito)
        self.ignore_explicit = False   # ignora anche l'unload esplicito
        self.loaded = False
        self._linger_left = 0
        self.chat_requests = []
        self.explicit_unloads = 0
        self.ps_calls = 0

    def app(self):
        app = web.Application()
        app.router.add_post("/api/chat", self.chat)
        app.router.add_get("/api/ps", self.ps)
        return app

    async def chat(self, request):
        import asyncio
        body = await request.json()
        self.chat_requests.append(body)
        if body.get("messages") == []:                     # unload esplicito
            self.explicit_unloads += 1
            self.log.append("llm_unload_explicit")
            if not self.ignore_explicit:
                self.loaded = False
            return web.json_response({"done": True, "done_reason": "unload",
                                      "message": {"role": "assistant", "content": ""}})
        self.log.append("llm_chat_start")
        self.loaded = True
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.chat_status == 404:
            self.loaded = False
            return web.json_response({"error": f"model '{self.model}' not found"}, status=404)
        if self.chat_status != 200:
            return web.json_response({"error": "boom"}, status=self.chat_status)
        if body.get("keep_alive") == 0 and not self.sticky:
            self._linger_left = self.linger_polls          # si scarica dopo qualche poll di /api/ps
            if self.linger_polls == 0:
                self.loaded = False
        self.log.append("llm_chat_end")
        return web.json_response({"model": self.model, "done": True, "done_reason": "stop",
                                  "message": {"role": "assistant", "content": self.content}})

    async def ps(self, request):
        self.ps_calls += 1
        if self.loaded and self._linger_left > 0:
            self._linger_left -= 1
            if self._linger_left == 0:
                self.loaded = False
                self.log.append("ps:empty")
                return web.json_response({"models": []})
        self.log.append("ps:loaded" if self.loaded else "ps:empty")
        models = [{"name": self.model, "model": self.model, "size_vram": 5_000_000_000}] if self.loaded else []
        return web.json_response({"models": models})


class FakeAnthropic:
    """
    API Messages di Anthropic finta (POST /v1/messages, anche nella variante beta ?beta=true).
    Registra ogni richiesta (header, query, body) per verificare il contratto, e un log eventi condiviso.
    """

    GOOD = FakeOllama.GOOD

    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.content = self.GOOD
        self.blocks = None               # blocchi `content` personalizzati
        self.stop_reason = "end_turn"
        self.status = 200
        self.error_type = "api_error"
        self.error_message = "boom detail con dati interni"
        self.delay = 0.0
        self.reject_fallbacks = False    # 400 se la richiesta contiene `fallbacks`
        self.requests = []

    def app(self):
        app = web.Application()
        app.router.add_post("/v1/messages", self.messages)
        return app

    def _error(self, status, error_type, message):
        return web.json_response({"type": "error", "error": {"type": error_type, "message": message}},
                                 status=status)

    async def messages(self, request):
        import asyncio
        body = await request.json()
        headers = {k.lower(): v for k, v in request.headers.items()}      # gli header HTTP non distinguono le maiuscole
        self.requests.append({"headers": headers, "query": dict(request.query), "body": body})
        self.log.append("claude_call")
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.reject_fallbacks and "fallbacks" in body:
            return self._error(400, "invalid_request_error", "fallbacks: not supported for this account")
        if self.status != 200:
            return self._error(self.status, self.error_type, self.error_message)
        content = self.blocks if self.blocks is not None else [{"type": "text", "text": self.content}]
        return web.json_response({
            "id": "msg_test", "type": "message", "role": "assistant", "model": body.get("model"),
            "content": content, "stop_reason": self.stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 20},
        })
