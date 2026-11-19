"""
Wrapper REST di HeartMuLa 3B (heartlib) con lo stesso contratto di ACE-Step 1.5, così il bot usa lo
stesso client: POST /release_task, POST /query_result, GET /v1/audio, GET /health (busta {data, code, error}).

Gira nel venv di heartlib, NON in quello del bot (dipendenze incompatibili):

    HEARTMULA_CKPT=<heartlib>/ckpt <heartlib>/venv/bin/python src/heartmula_server.py --port 8003

Lo avvia il bot quando serve (cogs/ace_step_cog.py) e lo spegne per liberare la VRAM.
Il modello si carica alla prima richiesta e resta in memoria finché il processo vive. Un solo lavoro alla volta.
"""

import argparse
import asyncio
import json
import os
import random
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from aiohttp import web

OUT_DIR = Path(os.environ.get("HEARTMULA_OUT", Path.home() / ".cache" / "heartmula-out"))
KEEP_SECONDS = 3600                 # i brani consegnati si cancellano dopo un'ora
TOPK, TEMPERATURE = 50, 1.0
# Lo script ufficiale di heartlib usa cfg 3.0, il README 1.5. Ogni cfg != 1.0 raddoppia il batch e quindi la cache KV.
CFG_SCALE = float(os.environ.get("HEARTMULA_CFG_SCALE", "1.5"))
# ponytail: tag di stile e testo sono quelli dell'LLM del bot; nessun controllo qualità lato wrapper


def load_pipeline():
    """
    Carica HeartMuLa 3B, con le scelte misurate su RX 6600 (8 GB, RDNA2):
    - fp16 (HEARTMULA_MULA_DTYPE / HEARTMULA_CODEC_DTYPE): la RDNA2 non ha istruzioni bf16 native, e l'81% del tempo
      di un passo era un solo kernel di matmul bf16. In fp16 il LM va 3 volte più veloce.
    - pesi del LM in INT8 (torchao): in 16 bit il modello pesa ~7,5 GB e va in OOM. HEARTMULA_INT8=0 per disattivarlo.
    - niente torch.compile (HEARTMULA_COMPILE=1 per attivarlo): il primo passo costava ~60 s e il modello compilato
      resta referenziato, quindi la VRAM non si liberava e il secondo brano falliva. Senza è anche più veloce in totale.
    - LM e codec non stanno in VRAM insieme: tra una fase e l'altra passano in RAM (invece di essere riletti dal
      disco e quantizzati di nuovo, ~30 s per brano).
    """
    import gc

    import soundfile
    import torch
    import torchaudio
    from heartlib import HeartMuLaGenPipeline
    from heartlib.heartmula.modeling_heartmula import HeartMuLa

    # torchaudio 2.9 salva solo con torchcodec (non installato): heartlib chiama torchaudio.save(path, wav, sr)
    torchaudio.save = lambda path, wav, sr, **kw: soundfile.write(str(path), wav.detach().cpu().float().numpy().T, sr)
    if os.environ.get("HEARTMULA_COMPILE") != "1":
        HeartMuLaGenPipeline._apply_compile = lambda self, model: None

    base_mula, base_codec = HeartMuLaGenPipeline.mula.fget, HeartMuLaGenPipeline.codec.fget
    ram: dict = {}                        # modelli in RAM tra un brano e l'altro

    def mula(self):
        if self._mula is None and "mula" in ram:
            self._mula = ram.pop("mula").to(self.mula_device)
        if self._mula is None and os.environ.get("HEARTMULA_INT8", "1") != "0":
            from torchao.quantization import int8_weight_only, quantize_

            model = HeartMuLa.from_pretrained(self.mula_path, device_map="cpu", dtype=self.mula_dtype)
            quantize_(model.backbone, int8_weight_only())
            quantize_(model.decoder, int8_weight_only())
            model.to(self.mula_device)
            self._apply_compile(model)
            self._mula = model
        return base_mula(self)

    def codec(self):
        if self._codec is None and "codec" in ram:
            self._codec = ram.pop("codec").to(self.codec_device)
        return base_codec(self)

    def unload(self):
        for name, attr in (("mula", "_mula"), ("codec", "_codec")):
            model = getattr(self, attr)
            if model is None:
                continue
            for module in model.modules():
                if hasattr(module, "kv_cache"):
                    module.kv_cache = None        # la cache KV si rialloca a ogni brano: non va portata in RAM
            ram[name] = model.to("cpu")
            setattr(self, attr, None)
        gc.collect()
        torch.cuda.empty_cache()

    HeartMuLaGenPipeline.mula, HeartMuLaGenPipeline.codec = property(mula), property(codec)
    HeartMuLaGenPipeline._unload = unload

    device = torch.device("cuda")        # su ROCm "cuda" è la GPU AMD
    return HeartMuLaGenPipeline.from_pretrained(
        os.environ["HEARTMULA_CKPT"],
        device={"mula": device, "codec": device},
        dtype={"mula": getattr(torch, os.environ.get("HEARTMULA_MULA_DTYPE", "float16")),
               "codec": getattr(torch, os.environ.get("HEARTMULA_CODEC_DTYPE", "float16"))},
        version="3B",
        lazy_load=True,
    )


def tags_from_caption(caption: str) -> str:
    """heartlib vuole tag separati da virgola, senza spazi (e li mette in minuscolo da sé)."""
    return ",".join(part.strip() for part in caption.replace("\n", " ").split(",") if part.strip())


RESERVE_BYTES = 1024**3              # margine per le attivazioni durante la generazione


def plan_cache(pipe, job: dict) -> tuple[int, float]:
    """
    Dimensiona la cache KV sulla durata richiesta e sulla VRAM rimasta dopo il caricamento del modello.
    torchtune la alloca per 8192 token (circa 650 s di audio) con tutte le testate: oltre 5 GiB con la guida CFG,
    che sull'RX 6600 (8 GB) manda in OOM anche un brano da 30 s. Restituisce (max_len, cfg_scale effettivo).
    """
    import torch

    backbone = pipe.mula.backbone         # carica (e quantizza) il LM: serve per sapere quanta VRAM resta
    attn = backbone.layers[0].attn
    per_token = len(backbone.layers) * 2 * attn.num_heads * attn.head_dim * 2        # k+v in bf16
    frames = job["duration"] * 1000 // 80                                            # 80 ms per frame
    prompt_tokens = (len(job["lyrics"]) + len(job["caption"])) // 2 + 300            # stima per eccesso
    max_len = min(8192, prompt_tokens + frames + 128)
    free = torch.cuda.mem_get_info()[0] - RESERVE_BYTES
    cfg = CFG_SCALE
    if cfg != 1.0 and 2 * max_len * per_token > free:
        cfg = 1.0                         # senza CFG il batch è 1: la cache dimezza
    if max_len * per_token > free:
        raise RuntimeError(f"brano troppo lungo per la VRAM libera ({free / 2**30:.1f} GiB, serve {max_len * per_token / 2**30:.1f})")
    return max_len, cfg


def run_pipeline(pipe, job: dict) -> str:
    """Generazione bloccante (GPU): va eseguita in un thread. Restituisce il percorso del file."""
    import torch

    max_len, cfg_scale = plan_cache(pipe, job)
    pipe.mula.backbone.max_seq_len = max_len                      # heartlib alloca cache e maschera con questo valore
    torch.manual_seed(job["seed"])       # heartlib non ha un parametro seed
    path = OUT_DIR / f"{job['id']}.wav"  # wav: non richiede un backend mp3 in torchaudio
    with torch.no_grad():
        pipe(
            {"lyrics": job["lyrics"], "tags": tags_from_caption(job["caption"])},
            max_audio_length_ms=job["duration"] * 1000,
            save_path=str(path),
            topk=TOPK, temperature=TEMPERATURE, cfg_scale=cfg_scale,
        )
    return str(path)


def envelope(data=None, code: int = 200, error=None) -> web.Response:
    return web.json_response({"data": data, "code": code, "error": error, "timestamp": int(time.time()), "extra": None})


def make_app(load: Callable = load_pipeline, run: Callable = run_pipeline) -> web.Application:
    jobs: dict[str, dict] = {}
    queue: asyncio.Queue = asyncio.Queue()
    state = {"pipe": None}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def cleanup() -> None:
        for old in OUT_DIR.glob("*.wav"):
            if time.time() - old.stat().st_mtime > KEEP_SECONDS:
                old.unlink(missing_ok=True)

    async def worker() -> None:
        while True:
            job = await queue.get()
            try:
                if state["pipe"] is None:
                    state["pipe"] = await asyncio.to_thread(load)
                job["file"] = await asyncio.to_thread(run, state["pipe"], job)
                job["status"] = 1
            except Exception as e:        # il bot mostra solo "generazione fallita": il dettaglio sta nel log
                print(f"[heartmula] job {job['id']} fallito: {e!r}", flush=True)
                traceback.print_exc()
                job["status"] = 2

    async def health(_: web.Request) -> web.Response:
        return envelope({"status": "ok"})

    async def release_task(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            lyrics, caption = str(body["lyrics"]).strip(), str(body.get("prompt", "")).strip()
            duration = int(body.get("audio_duration", 120))
        except (ValueError, KeyError, TypeError):
            return envelope(code=400, error="richiesta non valida")
        if not lyrics or not caption or not 10 <= duration <= 600:
            return envelope(code=400, error="richiesta non valida")
        cleanup()
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"id": job_id, "status": 0, "lyrics": lyrics, "caption": caption, "duration": duration,
                        "seed": random.randrange(2**31)}
        queue.put_nowait(jobs[job_id])
        return envelope({"task_id": job_id, "status": "queued", "queue_position": queue.qsize()})

    async def query_result(request: web.Request) -> web.Response:
        try:
            ids = (await request.json())["task_id_list"]
        except (ValueError, KeyError, TypeError):
            return envelope(code=400, error="richiesta non valida")
        items = []
        for job_id in ids:
            job = jobs.get(job_id)
            if job is None:
                continue
            inner = {"status": job["status"]}
            if job["status"] == 1:
                inner.update(file=f"/v1/audio?path={quote(job['file'], safe='')}", metas={"duration": job["duration"]})
            items.append({"task_id": job_id, "status": job["status"], "result": json.dumps([inner])})
        return envelope(items)

    async def audio(request: web.Request) -> web.Response:
        path = Path(request.query.get("path", "")).resolve()
        if OUT_DIR.resolve() not in path.parents or not path.is_file():      # niente file fuori dalla cartella dei brani
            raise web.HTTPForbidden()
        return web.FileResponse(path)

    async def start(app: web.Application) -> None:
        app["worker"] = asyncio.create_task(worker())

    async def stop(app: web.Application) -> None:
        app["worker"].cancel()

    app = web.Application()
    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.add_routes([web.get("/health", health), web.post("/release_task", release_task),
                    web.post("/query_result", query_result), web.get("/v1/audio", audio)])
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8003)
    web.run_app(make_app(), host="127.0.0.1", port=parser.parse_args().port)
