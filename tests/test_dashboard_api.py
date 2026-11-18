"""Test della dashboard: login, CSRF, upload in streaming, API di suoni/voci/modelli, scritture concorrenti."""

import asyncio
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

import cogs
import storage
from audio_samples import MP3, wav_bytes, zip_bytes
from dashboard import ConfigError, DashboardConfig, create_app
from dashboard.app import BOT_KEY, LIMITER_KEY
from dashboard.auth import SessionStore
from database import Database

PASSWORD = "correct horse battery"
MODEL_ZIP = zip_bytes({"voce.pth": b"pesi" * 50, "voce.index": b"idx"})


class Api:
    """Piccolo client: ricorda il token CSRF dopo il login."""

    def __init__(self, client):
        self.client, self.csrf = client, None
        self.origin = str(client.make_url("/")).rstrip("/")

    def headers(self, csrf=True, **extra):
        h = {"Origin": self.origin}
        if csrf and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        h.update(extra)                     # `extra` può sostituire anche il token (per i test)
        return h

    async def login(self, password=PASSWORD):
        r = await self.client.post("/api/login", json={"password": password}, headers=self.headers(csrf=False))
        if r.status == 200:
            self.csrf = (await r.json())["csrf"]
        return r

    async def call(self, method, path, expect=None, **kwargs):
        headers = kwargs.pop("headers", None) or self.headers()
        r = await self.client.request(method, path, headers=headers, **kwargs)
        data = await r.json() if r.content_type == "application/json" else await r.read()
        if expect is not None:
            assert r.status == expect, (r.status, data)
        return r.status, data

    def get(self, path, **kw): return self.call("GET", path, **kw)
    def post(self, path, **kw): return self.call("POST", path, **kw)
    def patch(self, path, **kw): return self.call("PATCH", path, **kw)
    def delete(self, path, **kw): return self.call("DELETE", path, **kw)


def form(data: bytes, filename="x.wav", **fields):
    fd = aiohttp.FormData()
    for key, value in fields.items():
        fd.add_field(key, value)
    fd.add_field("file", data, filename=filename, content_type="application/octet-stream")
    return fd


@pytest.fixture
async def dash(tmp_path, monkeypatch):
    monkeypatch.setattr(cogs, "BASE_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "RVC_MODELS_DIR", tmp_path / "models")
    db = await Database.open(tmp_path / "t.sqlite3")
    config = DashboardConfig(password=PASSWORD, fail_delay=0)
    app = create_app(db, config)
    client = TestClient(TestServer(app))
    await client.start_server()
    api = Api(client)
    await storage.sync_guilds(db, [(7, "Casa", None, 5), (8, "Ufficio", None, 3)])
    yield SimpleNamespace(client=client, api=api, db=db, app=app, config=config, tmp=tmp_path)
    await client.close()
    await db.aclose()


@pytest.fixture
async def api(dash):
    await dash.api.login()
    return dash.api


def leftover_uploads(dash):
    folder = dash.tmp / "data" / ".uploads"
    return list(folder.iterdir()) if folder.exists() else []


# ------------------------------------------------------------------------------ login

ROUTES = [("GET", "/api/overview"), ("GET", "/api/guilds"), ("GET", "/api/audit"), ("GET", "/api/sounds"),
          ("GET", "/api/voices"), ("GET", "/api/rvc"), ("POST", "/api/sounds"), ("POST", "/api/voices"),
          ("POST", "/api/rvc"), ("POST", "/api/rvc/scan"), ("PATCH", "/api/sounds/1"), ("DELETE", "/api/sounds/1"),
          ("GET", "/api/sounds/1/audio"), ("PATCH", "/api/voices/1"), ("DELETE", "/api/voices/1"),
          ("GET", "/api/voices/1/audio"), ("PATCH", "/api/rvc/1"), ("DELETE", "/api/rvc/1")]


async def test_every_api_route_requires_login(dash):
    for method, path in ROUTES:
        status, data = await dash.api.call(method, path)
        assert status == 401 and data["error"], (method, path)


async def test_the_page_and_the_session_probe_are_public(dash):
    r = await dash.client.get("/")
    assert r.status == 200 and "text/html" in r.content_type
    status, data = await dash.api.get("/api/session")
    assert status == 200 and data == {"authenticated": False, "csrf": None}


async def test_login_wrong_password_and_garbage(dash):
    dash.app[LIMITER_KEY].max_failures = 100
    for body in ({"password": "sbagliata"}, {"password": ""}, {"password": 123}, {"password": None}, {}):
        r = await dash.client.post("/api/login", json=body, headers=dash.api.headers(csrf=False))
        assert r.status == 401 and "driftbot_session" not in r.cookies
    r = await dash.client.post("/api/login", data="non json", headers=dash.api.headers(csrf=False))
    assert r.status == 400
    r = await dash.client.post("/api/login", json=["lista"], headers=dash.api.headers(csrf=False))
    assert r.status == 400


async def test_login_sets_a_hardened_cookie_and_session_works(dash):
    r = await dash.api.login()
    cookie = r.headers["Set-Cookie"]
    assert r.status == 200 and "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie
    status, data = await dash.api.get("/api/session")
    assert data["authenticated"] is True and data["csrf"] == dash.api.csrf
    await dash.api.get("/api/overview", expect=200)


async def test_cookie_is_secure_when_configured(dash):
    dash.config.cookie_secure = True
    r = await dash.api.login()
    assert "Secure" in r.headers["Set-Cookie"]


async def test_brute_force_is_throttled_even_for_the_right_password(dash):
    dash.app[LIMITER_KEY].max_failures, dash.app[LIMITER_KEY].lockout = 3, 0.4
    for _ in range(3):
        assert (await dash.api.login("no")).status == 401
    r = await dash.api.login()                     # password giusta, ma l'indirizzo è bloccato
    body = await r.json()
    assert r.status == 429 and body["retry_after"] >= 1
    await asyncio.sleep(0.45)
    assert (await dash.api.login()).status == 200  # finito il blocco si può entrare


async def test_a_successful_login_resets_the_failure_counter(dash):
    dash.app[LIMITER_KEY].max_failures, dash.app[LIMITER_KEY].lockout = 3, 60
    for _ in range(2):
        await dash.api.login("no")
    assert (await dash.api.login()).status == 200
    for _ in range(2):
        assert (await dash.api.login("no")).status == 401     # il contatore era ripartito da zero


async def test_logout_invalidates_the_session(dash, api):
    await api.post("/api/logout", expect=200)
    await api.get("/api/overview", expect=401)


async def test_sessions_expire_and_are_capped():
    now = [0.0]
    store = SessionStore(ttl=10, clock=lambda: now[0])
    first = store.create()
    assert store.get(first.token) is first and store.get("sconosciuto") is None and store.get(None) is None
    now[0] = 11
    assert store.get(first.token) is None
    for _ in range(80):
        store.create()
    assert len(store) <= 50


# ------------------------------------------------------------------------------- CSRF

async def test_state_changing_requests_need_the_csrf_token(dash, api):
    status, data = await api.post("/api/sounds", data=form(wav_bytes(), name="a"), headers=api.headers(csrf=False))
    assert status == 403 and "CSRF" in data["error"]
    status, _ = await api.post("/api/sounds", data=form(wav_bytes(), name="a"), headers=api.headers(**{"X-CSRF-Token": "sbagliato"}))
    assert status == 403
    await api.post("/api/sounds", data=form(wav_bytes(), name="a", scope="global"), expect=201)
    sound = (await api.get("/api/sounds"))[1]["sounds"][0]
    assert (await api.delete(f"/api/sounds/{sound['id']}", headers=api.headers(csrf=False)))[0] == 403
    assert len((await api.get("/api/sounds"))[1]["sounds"]) == 1          # non è stato cancellato
    assert (await api.patch(f"/api/sounds/{sound['id']}", json={"name": "x"}, headers=api.headers(csrf=False)))[0] == 403
    assert (await api.post("/api/rvc/scan", headers=api.headers(csrf=False)))[0] == 403


async def test_cross_site_requests_are_refused_even_with_a_valid_token(dash, api):
    evil = api.headers(Origin="https://evil.example")
    for method, path in (("POST", "/api/rvc/scan"), ("DELETE", "/api/sounds/1"), ("PATCH", "/api/voices/1")):
        status, _ = await api.call(method, path, headers=evil)
        assert status == 403
    r = await dash.client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": "https://evil.example"})
    assert r.status == 403


async def test_security_headers_everywhere(dash, api):
    for path in ("/", "/api/overview", "/api/nope", "/static/nope.js"):
        r = await dash.client.get(path)
        assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'none'" in r.headers["Content-Security-Policy"] and "unsafe" not in r.headers["Content-Security-Policy"]
    assert (await dash.client.get("/api/overview")).headers["Cache-Control"] == "no-store"


async def test_unknown_api_routes_answer_with_json(dash, api):
    r = await dash.client.get("/api/nope", headers=api.headers())
    assert r.status in (401, 404) and r.content_type == "application/json"
    status, data = await api.get("/api/rvc/1", expect=405)
    assert "error" in data


# ------------------------------------------------------------------------------- suoni

async def test_sound_lifecycle(dash, api):
    _, data = await api.post("/api/sounds", data=form(wav_bytes(), "airhorn.wav", name="Airhorn", scope="global"), expect=201)
    sound = data["sound"]
    assert sound["name"] == "Airhorn" and sound["guild_id"] == 0 and sound["format"] == "wav" and "filename" not in sound

    status, audio = await api.get(f"/api/sounds/{sound['id']}/audio", expect=200)
    assert audio == wav_bytes()
    r = await dash.client.get(f"/api/sounds/{sound['id']}/audio", headers={"Range": "bytes=0-9"})
    assert r.status == 206 and r.headers["Content-Type"] == "audio/wav" and "inline" in r.headers["Content-Disposition"]

    _, data = await api.patch(f"/api/sounds/{sound['id']}", json={"name": "Tromba"}, expect=200)
    assert data["sound"]["name"] == "Tromba"
    _, data = await api.patch(f"/api/sounds/{sound['id']}", json={"scope": "7"}, expect=200)
    assert data["sound"]["guild_id"] == 7
    _, data = await api.patch(f"/api/sounds/{sound['id']}", json={"scope": "global", "name": "Di nuovo"}, expect=200)
    assert (data["sound"]["guild_id"], data["sound"]["name"]) == (0, "Di nuovo")

    _, listing = await api.get("/api/sounds?scope=global", expect=200)
    assert [s["name"] for s in listing["sounds"]] == ["Di nuovo"]
    assert (await api.get("/api/sounds?scope=7"))[1]["sounds"] == []
    await api.delete(f"/api/sounds/{sound['id']}", expect=200)
    assert (await api.get("/api/sounds"))[1]["sounds"] == []
    assert list((dash.tmp / "data" / "global" / "soundboard").iterdir()) == []         # file eliminato dal disco
    await api.delete(f"/api/sounds/{sound['id']}", expect=404)


async def test_sound_name_defaults_to_the_file_name_and_scope_to_global(dash, api):
    _, data = await api.post("/api/sounds", data=form(MP3, "bella-canzone.mp3"), expect=201)
    assert data["sound"]["name"] == "bella-canzone" and data["sound"]["guild_id"] == 0 and data["sound"]["format"] == "mp3"


async def test_bad_sound_uploads_are_rejected_without_leaving_files(dash, api, monkeypatch):
    status, data = await api.post("/api/sounds", data=form(b"MZ non audio", "virus.wav", name="x"))
    assert status == 400 and "Formato" in data["error"]
    assert (await api.post("/api/sounds", data=form(b"", "v.wav", name="x")))[0] == 400
    assert (await api.post("/api/sounds", data=form(wav_bytes(), name="x", scope="abc")))[0] == 400
    assert (await api.post("/api/sounds", data=form(wav_bytes(), name="x", scope="999")))[0] == 404     # server sconosciuto
    assert (await api.post("/api/sounds", data=form(wav_bytes(), name="   ")))[0] == 201                # nome vuoto -> nome del file
    only_name = aiohttp.FormData()
    only_name.add_field("name", "senza file")
    assert (await api.post("/api/sounds", data=only_name))[0] == 400
    assert (await api.post("/api/sounds", json={"name": "x"}))[0] == 400                                # non è multipart
    two = aiohttp.FormData()
    two.add_field("file", wav_bytes(), filename="a.wav")
    two.add_field("file", wav_bytes(), filename="b.wav")
    assert (await api.post("/api/sounds", data=two))[0] == 400

    monkeypatch.setattr(storage, "MAX_SOUND_BYTES", 2000)
    status, data = await api.post("/api/sounds", data=form(wav_bytes(1), name="grande"))
    assert status == 413 and "limite" in data["error"]
    assert leftover_uploads(dash) == []                                    # nessun file temporaneo rimasto
    assert len((await api.get("/api/sounds"))[1]["sounds"]) == 1           # solo quello valido


async def test_duplicate_sound_name_is_a_conflict_and_cleans_up(dash, api):
    await api.post("/api/sounds", data=form(wav_bytes(), name="Clap", scope="7"), expect=201)
    status, data = await api.post("/api/sounds", data=form(wav_bytes(), name="clap", scope="7"))
    assert status == 409 and "clap" in data["error"]
    assert leftover_uploads(dash) == [] and len(list((dash.tmp / "data" / "7" / "soundboard").iterdir())) == 1


async def test_hostile_names_are_stored_verbatim_and_never_become_paths(dash, api):
    for name in ("<script>alert(1)</script>", "../../etc/passwd", "a/b\\c", "🎺 ok"):
        _, data = await api.post("/api/sounds", data=form(wav_bytes(), "../../../x.wav", name=name), expect=201)
        assert data["sound"]["name"] == name
    root = dash.tmp / "data"
    assert sorted(p.name for p in root.iterdir() if p.name != ".uploads") == ["global"]
    assert len(list((root / "global" / "soundboard").iterdir())) == 4          # nomi file generati dal server
    assert not (dash.tmp / "x.wav").exists() and not (dash.tmp.parent / "x.wav").exists()


async def test_audio_endpoints_with_garbage_ids_and_missing_files(dash, api):
    for bad in ("abc", "..%2F..%2Fetc%2Fpasswd", "0", "99999"):
        assert (await api.get(f"/api/sounds/{bad}/audio"))[0] == 404
    _, data = await api.post("/api/sounds", data=form(wav_bytes(), name="x"), expect=201)
    (next((dash.tmp / "data" / "global" / "soundboard").iterdir())).unlink()
    status, body = await api.get(f"/api/sounds/{data['sound']['id']}/audio")
    assert status == 404 and "disco" in body["error"]
    assert (await api.get("/api/sounds"))[1]["sounds"][0]["missing"] is True


async def test_sound_update_validation(dash, api):
    _, data = await api.post("/api/sounds", data=form(wav_bytes(), name="A"), expect=201)
    sid = data["sound"]["id"]
    assert (await api.patch(f"/api/sounds/{sid}", json={}))[0] == 400
    assert (await api.patch(f"/api/sounds/{sid}", json={"name": ""}))[0] == 400
    assert (await api.patch(f"/api/sounds/{sid}", json={"scope": "boh"}))[0] == 400
    assert (await api.patch(f"/api/sounds/{sid}", json={"scope": "999"}))[0] == 404
    assert (await api.patch("/api/sounds/999", json={"name": "x"}))[0] == 404
    assert (await api.patch(f"/api/sounds/{sid}", data="non json"))[0] == 400
    await api.post("/api/sounds", data=form(wav_bytes(), name="B", scope="7"), expect=201)
    _, d2 = await api.post("/api/sounds", data=form(wav_bytes(), name="B"), expect=201)
    assert (await api.patch(f"/api/sounds/{d2['sound']['id']}", json={"scope": "7"}))[0] == 409


# -------------------------------------------------------------------------------- voci

async def test_voice_lifecycle(dash, api):
    _, data = await api.post("/api/voices", data=form(wav_bytes(2), "mario.wav", name="Mario", guild="7"), expect=201)
    voice = data["voice"]
    assert voice["guild_id"] == 7 and voice["duration"] == pytest.approx(2.0)
    assert (await api.get(f"/api/voices/{voice['id']}/audio", expect=200))[1] == wav_bytes(2)
    assert (await api.get("/api/voices?guild=8"))[1]["voices"] == []
    assert len((await api.get("/api/voices"))[1]["voices"]) == 1
    _, data = await api.patch(f"/api/voices/{voice['id']}", json={"name": "Super Mario"}, expect=200)
    assert data["voice"]["name"] == "Super Mario"
    await api.delete(f"/api/voices/{voice['id']}", expect=200)
    assert list((dash.tmp / "data" / "7" / "speakers").iterdir()) == []


async def test_voice_validation(dash, api):
    assert (await api.post("/api/voices", data=form(wav_bytes(), name="x", guild="global")))[0] == 400
    assert (await api.post("/api/voices", data=form(wav_bytes(), name="x")))[0] == 400            # server mancante
    assert (await api.post("/api/voices", data=form(wav_bytes(), name="x", guild="999")))[0] == 404
    assert (await api.get("/api/voices?guild=global"))[0] == 400
    await api.post("/api/voices", data=form(wav_bytes(), name="Mario", guild="7"), expect=201)
    assert (await api.post("/api/voices", data=form(wav_bytes(), name="mario", guild="7")))[0] == 409
    await api.post("/api/voices", data=form(wav_bytes(), name="Mario", guild="8"), expect=201)    # altro server: ok
    assert (await api.patch("/api/voices/1", json={}))[0] == 400
    assert leftover_uploads(dash) == []


# --------------------------------------------------------------------------- modelli RVC

async def test_model_lifecycle(dash, api):
    _, data = await api.post("/api/rvc", data=form(MODEL_ZIP, "m.zip", name="Voce Uno", description="prova", guild_ids="7, 8"), expect=201)
    model = data["model"]
    assert model["guild_ids"] == [7, 8] and model["enabled"] is True and model["missing"] is False and "folder" not in model
    assert (dash.tmp / "models").is_dir()

    _, data = await api.patch(f"/api/rvc/{model['id']}", json={"enabled": False, "name": "Voce Due", "guild_ids": [7]}, expect=200)
    assert (data["model"]["enabled"], data["model"]["name"], data["model"]["guild_ids"]) == (False, "Voce Due", [7])
    assert [m["name"] for m in await storage.list_rvc_models(dash.db, 8, usable_only=True)] == []
    assert (await api.get("/api/rvc"))[1]["models"][0]["name"] == "Voce Due"

    await api.delete(f"/api/rvc/{model['id']}", expect=200)
    assert [p for p in (dash.tmp / "models").iterdir()] == []
    await api.delete(f"/api/rvc/{model['id']}", expect=404)


async def test_model_validation_and_scan(dash, api, monkeypatch):
    assert (await api.post("/api/rvc", data=form(b"non uno zip", "m.zip", name="x")))[0] == 400
    assert (await api.post("/api/rvc", data=form(zip_bytes({"a.txt": b"x"}), "m.zip", name="x")))[0] == 400
    assert (await api.post("/api/rvc", data=form(MODEL_ZIP, "m.zip", name="x", guild_ids="7,abc")))[0] == 400
    assert (await api.post("/api/rvc", data=form(MODEL_ZIP, "m.zip", name="x", guild_ids="999")))[0] == 404
    assert (await api.post("/api/rvc", data=form(MODEL_ZIP, "m.exe", name="x")))[0] == 400
    monkeypatch.setattr(storage, "MAX_RVC_BYTES", 500)
    assert (await api.post("/api/rvc", data=form(b"0" * 3000, "m.pth", name="grande")))[0] == 413
    assert leftover_uploads(dash) == [] and (await api.get("/api/rvc"))[1]["models"] == []

    (dash.tmp / "models" / "copiato-a-mano").mkdir(parents=True)
    (dash.tmp / "models" / "copiato-a-mano" / "x.pth").write_bytes(b"x")
    _, scan = await api.post("/api/rvc/scan", expect=200)
    assert scan == {"added": ["copiato-a-mano"], "missing": []}
    assert (await api.patch("/api/rvc/1", json={"enabled": "si"}))[0] == 400
    assert (await api.patch("/api/rvc/1", json={"description": 5}))[0] == 400
    assert (await api.patch("/api/rvc/1", json={}))[0] == 400
    assert (await api.patch("/api/rvc/999", json={"enabled": True}))[0] == 404


# ------------------------------------------------------------------- server, registro, stato

async def test_overview_guilds_and_audit(dash, api):
    await api.post("/api/sounds", data=form(wav_bytes(), name="A", scope="7"), expect=201)
    _, data = await api.get("/api/overview", expect=200)
    assert data["counts"]["sounds"] == 1 and data["counts"]["guilds"] == 2
    assert data["db"]["journal_mode"] == "wal" and data["db"]["writes_done"] >= 1
    assert data["bot"] == {"connected": False} and data["limits"]["sound_mb"] == 8
    _, data = await api.get("/api/guilds", expect=200)
    assert {g["name"]: g["sounds"] for g in data["guilds"]} == {"Casa": 1, "Ufficio": 0}
    _, data = await api.get("/api/audit?limit=5", expect=200)
    assert [(e["actor"], e["action"]) for e in data["entries"][:2]] == [("dashboard", "sound.add"), ("dashboard", "login")]
    assert (await api.get("/api/audit?limit=boh"))[0] == 400


@pytest.mark.filterwarnings("ignore:Changing state of started")
async def test_overview_reports_the_bot_when_attached(dash, api):
    dash.app[BOT_KEY] = SimpleNamespace(is_ready=lambda: True, latency=0.0421, user="DriftBot#1234")
    _, data = await api.get("/api/overview", expect=200)
    assert data["bot"] == {"connected": True, "latency_ms": 42, "user": "DriftBot#1234"}
    dash.app[BOT_KEY] = SimpleNamespace(is_ready=lambda: 1 / 0)
    assert (await api.get("/api/overview"))[1]["bot"] == {"connected": False}


# ---------------------------------------------------------------- scritture concorrenti via HTTP

async def test_many_simultaneous_uploads_all_succeed(dash, api):
    """Più persone che caricano insieme: le scritture passano dalla coda, nessun errore 'database is locked'."""
    async def one(i):
        return await api.post("/api/sounds", data=form(wav_bytes(), f"s{i}.wav", name=f"Suono {i}", scope=str(7 + i % 2)))

    results = await asyncio.gather(*(one(i) for i in range(40)))
    assert all(status == 201 for status, _ in results), [r for r in results if r[0] != 201][:2]
    assert len(await storage.list_sounds(dash.db)) == 40
    on_disk = sum(len(list((dash.tmp / "data" / g / "soundboard").iterdir())) for g in ("7", "8"))
    assert on_disk == 40 and leftover_uploads(dash) == []
    assert (await storage.overview(dash.db))["sounds"] == 40


async def test_simultaneous_uploads_of_the_same_name_create_one(dash, api):
    results = await asyncio.gather(*(
        api.post("/api/sounds", data=form(wav_bytes(), name="Stesso", scope="7")) for _ in range(15)
    ))
    statuses = sorted(s for s, _ in results)
    assert statuses == [201] + [409] * 14
    assert len(list((dash.tmp / "data" / "7" / "soundboard").iterdir())) == 1 and leftover_uploads(dash) == []


async def test_dashboard_and_bot_side_writes_interleave(dash, api):
    """La dashboard carica mentre il «bot» scrive sulla stessa base dati (via storage): niente si perde."""
    async def bot_side(i):
        path = dash.tmp / f"bot-{i}.wav"
        path.write_bytes(wav_bytes())
        await storage.add_sound(dash.db, 8, f"Bot {i}", path)

    async def dash_side(i):
        return await api.post("/api/sounds", data=form(wav_bytes(), name=f"Dash {i}", scope="7"))

    results = await asyncio.gather(*(bot_side(i) for i in range(25)), *(dash_side(i) for i in range(25)))
    assert all(r[0] == 201 for r in results[25:])
    assert len(await storage.list_sounds(dash.db)) == 50


# ----------------------------------------------------------------------- configurazione

def test_config_from_env():
    cfg = DashboardConfig.from_env({"DASHBOARD_PASSWORD": "abcdefgh", "DASHBOARD_PORT": "9000",
                                    "DASHBOARD_HOST": "0.0.0.0", "DASHBOARD_COOKIE_SECURE": "true"})
    assert (cfg.host, cfg.port, cfg.cookie_secure, cfg.trust_proxy) == ("0.0.0.0", 9000, True, False)
    default = DashboardConfig.from_env({"DASHBOARD_PASSWORD": "abcdefgh"})
    assert (default.host, default.port, default.cookie_secure) == ("127.0.0.1", 8080, False)
    for bad in ({}, {"DASHBOARD_PASSWORD": ""}, {"DASHBOARD_PASSWORD": "corta"},
                {"DASHBOARD_PASSWORD": "abcdefgh", "DASHBOARD_PORT": "x"},
                {"DASHBOARD_PASSWORD": "abcdefgh", "DASHBOARD_PORT": "70000"}):
        with pytest.raises(ConfigError):
            DashboardConfig.from_env(bad)
