"""
Test della dashboard NEL BROWSER (Chromium via Playwright): login, caricamenti, modifica, eliminazione,
accessibilità, XSS, sessione scaduta, layout da telefono.

Vengono saltati se Playwright o Chromium non sono installati (in CI non lo sono). Per eseguirli:
    pip install playwright && playwright install chromium
    DRIFTBOT_E2E_CHROMIUM=/percorso/di/chrome   (facoltativo: usa un Chromium già presente)
"""

import os

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import storage  # noqa: E402
from audio_samples import MP3, wav_bytes, zip_bytes  # noqa: E402
from live_dashboard import PASSWORD, LiveDashboard  # noqa: E402

expect = sync_api.expect


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            exe = os.getenv("DRIFTBOT_E2E_CHROMIUM") or None
            b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        except Exception as e:      # noqa: BLE001
            pytest.skip(f"Chromium non disponibile: {e}")
        yield b
        b.close()


@pytest.fixture
def live():
    server = LiveDashboard().start()
    yield server
    server.stop()


class Page:
    """Pagina del browser + elenco dei problemi di console (CSP violata, errori JS...)."""

    def __init__(self, browser, live, **context_args):
        self.context = browser.new_context(**context_args)
        self.page = self.context.new_page()
        self.problems: list[str] = []
        self.expected = ["the server responded with a status of 401"]
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.live = live
        self.page.goto(live.url)

    # Il browser registra in console ogni risposta 401 (password sbagliata, sessione scaduta): è atteso nei test
    # che li provocano. Tutto il resto (CSP violata, errori JS, risorse mancanti) è un problema vero.
    def allow(self, *statuses: int) -> "Page":
        """Dichiara attesi altri errori HTTP (es. un 409 per un nome doppio che il test provoca apposta)."""
        self.expected += [f"the server responded with a status of {s}" for s in statuses]
        return self

    def _on_console(self, message):
        if message.type in ("error", "warning") and not any(text in message.text for text in self.expected):
            self.problems.append(message.text)

    def login(self, password=PASSWORD):
        self.page.fill("#login-password", password)
        self.page.click("#login-form button[type=submit]")

    def logged_in(self):
        self.login()
        expect(self.page.locator("#app-view")).to_be_visible()
        return self

    def go(self, route):
        self.page.goto(f"{self.live.url}/#/{route}")
        expect(self.page.locator("#main .loading")).to_have_count(0)
        return self.page


@pytest.fixture
def make_page(browser, live):
    pages = []

    def make(**context_args):
        pages.append(Page(browser, live, **context_args))
        return pages[-1]

    yield make
    for p in pages:
        assert p.problems == [], p.problems          # nessun errore di console / violazione della CSP
        p.context.close()


@pytest.fixture
def app(make_page):
    return make_page(viewport={"width": 1280, "height": 800}).logged_in()


def file_payload(name, data, mime="application/octet-stream"):
    return {"name": name, "mimeType": mime, "buffer": data}


# --------------------------------------------------------------------------- accesso

def test_login_rejects_a_wrong_password_and_remembers_the_session(make_page):
    p = make_page()
    page = p.page
    expect(page.locator("#login-view")).to_be_visible()
    expect(page.locator("#app-view")).to_be_hidden()
    p.login("sbagliata")
    expect(page.get_by_role("alert")).to_have_text("Password errata.")
    expect(page.locator("#app-view")).to_be_hidden()
    p.login()
    expect(page.locator("#app-view")).to_be_visible()
    expect(page.get_by_role("heading", name="Panoramica", level=1)).to_be_visible()
    page.reload()                                        # il cookie di sessione basta: niente nuovo login
    expect(page.locator("#app-view")).to_be_visible()
    page.get_by_role("button", name="Esci").click()
    expect(page.locator("#login-view")).to_be_visible()
    page.reload()
    expect(page.locator("#login-view")).to_be_visible()


def test_every_section_renders(app):
    expected = {"panoramica": "Panoramica", "soundboard": "Soundboard", "voci": "Voci clonate",
                "rvc": "Modelli RVC", "server": "Server", "registro": "Registro"}
    for route, title in expected.items():
        page = app.go(route)
        expect(page.get_by_role("heading", level=1)).to_have_text(title)
        expect(page.get_by_role("link", name=title, exact=True).first).to_have_attribute("aria-current", "page")
    page = app.go("panoramica")
    expect(page.get_by_text("Modalità")).to_be_visible()
    expect(page.get_by_text("WAL", exact=True)).to_be_visible()
    app.go("server")
    expect(app.page.get_by_role("heading", name="Casa di Gigi")).to_be_visible()
    expect(app.page.get_by_text("Non presente")).to_be_visible()


# ---------------------------------------------------------------------------- suoni

def test_sound_upload_edit_move_and_delete(app, live):
    page = app.go("soundboard")
    expect(page.get_by_role("row")).to_have_count(6)               # intestazione + 5 suoni di esempio

    page.fill("#new-sound-name", "Fanfara")
    page.select_option("#new-sound-scope", label="Casa di Gigi")
    page.set_input_files("#new-sound-file", file_payload("fanfara.wav", wav_bytes(1)))
    expect(page.locator(".dropzone .file-name")).to_have_text("fanfara.wav")
    page.get_by_role("button", name="Carica suono").click()
    expect(page.locator("#toasts")).to_contain_text("Caricato con successo")
    row = page.get_by_role("row", name="Fanfara")
    expect(row).to_contain_text("Casa di Gigi")
    expect(page.locator(".dropzone .file-name")).to_have_text("Nessun file scelto")      # modulo ripulito

    # modifica: rinomina e rende globale
    page.get_by_role("button", name="Modifica Fanfara").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_label("Nome").fill("Fanfara reale")
    dialog.get_by_label("Dove è disponibile").select_option(label="🌐 Globale (tutti i server)")
    dialog.get_by_role("button", name="Salva").click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("row", name="Fanfara reale")).to_contain_text("Globale")

    # eliminazione: Esc annulla, poi si conferma
    page.get_by_role("button", name="Elimina Fanfara reale").click()
    expect(page.get_by_role("dialog")).to_contain_text("Eliminare il suono?")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_be_hidden()
    expect(page.get_by_role("row", name="Fanfara reale")).to_be_visible()
    page.get_by_role("button", name="Elimina Fanfara reale").click()
    page.get_by_role("dialog").get_by_role("button", name="Elimina").click()
    expect(page.locator("#toasts")).to_contain_text("Suono eliminato")
    expect(page.get_by_role("row", name="Fanfara reale")).to_have_count(0)
    assert "Fanfara reale" not in [s["name"] for s in live.run(storage.list_sounds(live.db))]


def test_duplicate_name_error_is_shown_in_the_dialog_and_the_form(app):
    app.allow(409)
    page = app.go("soundboard")
    page.fill("#new-sound-name", "AIRHORN")                         # esiste già (globale): maiuscole irrilevanti
    page.set_input_files("#new-sound-file", file_payload("x.wav", wav_bytes()))
    page.get_by_role("button", name="Carica suono").click()
    expect(page.locator("#toasts")).to_contain_text("Esiste già un suono chiamato")

    page.get_by_role("button", name="Modifica Vittoria").click()
    page.get_by_role("dialog").get_by_label("Dove è disponibile").select_option(label="🌐 Globale (tutti i server)")
    page.get_by_role("dialog").get_by_label("Nome").fill("airhorn")
    page.get_by_role("dialog").get_by_role("button", name="Salva").click()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_contain_text("ha già un suono chiamato")
    expect(page.get_by_role("dialog")).to_be_visible()              # resta aperto per correggere


def test_names_from_the_server_are_text_never_html(app, live):
    evil = '<img src=x onerror="window.__pwned=1"><b>grassetto</b>'
    page = app.go("soundboard")
    page.fill("#new-sound-name", evil)
    page.set_input_files("#new-sound-file", file_payload("a.mp3", MP3))
    page.get_by_role("button", name="Carica suono").click()
    expect(page.locator("td.cell-name", has_text="grassetto")).to_have_text(evil)
    assert page.evaluate("window.__pwned") is None
    assert page.locator("td.cell-name b").count() == 0
    app.go("registro")
    expect(page.locator("td.cell-name", has_text="grassetto").first).to_be_visible()
    assert page.evaluate("window.__pwned") is None


def test_filter_by_scope_through_the_url(app):
    page = app.go("soundboard")
    page.select_option("#sound-scope", label="🌐 Globale (tutti i server)")
    expect(page).to_have_url(f"{app.live.url}/#/soundboard?scope=global")
    expect(page.get_by_role("row")).to_have_count(3)
    expect(page.get_by_role("row", name="Applauso")).to_have_count(0)
    page.go_back()
    expect(page.get_by_role("row")).to_have_count(6)


def test_play_button_toggles(app):
    page = app.go("soundboard")
    button = page.get_by_role("button", name="Ascolta Sad trombone")
    expect(button).to_have_attribute("aria-pressed", "false")
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    button.click()
    expect(button).to_have_attribute("aria-pressed", "false")


# ------------------------------------------------------------------------------ voci

def test_voice_upload_validation_and_rename_delete(app, live):
    app.allow(400)
    page = app.go("voci")
    page.select_option("#new-voice-guild", label="Ufficio Gaming")
    page.set_input_files("#new-voice-file", file_payload("finto.wav", b"questo non e' audio"))
    page.get_by_role("button", name="Carica voce").click()
    expect(page.locator("#toasts")).to_contain_text("Formato audio non riconosciuto")
    expect(page.get_by_role("row", name="finto")).to_have_count(0)

    page.set_input_files("#new-voice-file", file_payload("Luca.wav", wav_bytes(65)))
    expect(page.locator("#new-voice-name")).to_have_value("Luca")          # nome proposto dal file
    page.get_by_role("button", name="Carica voce").click()
    row = page.get_by_role("row", name="Luca")
    expect(row).to_contain_text("Ufficio Gaming")
    expect(row).to_contain_text("1:05")

    page.get_by_role("button", name="Rinomina Luca").click()
    page.get_by_role("dialog").get_by_label("Nome della voce").fill("Luca Rossi")
    page.get_by_role("dialog").get_by_role("button", name="Salva").click()
    expect(page.get_by_role("row", name="Luca Rossi")).to_be_visible()
    page.get_by_role("button", name="Elimina Luca Rossi").click()
    page.get_by_role("dialog").get_by_role("button", name="Elimina").click()
    expect(page.get_by_role("row", name="Luca Rossi")).to_have_count(0)
    assert len(live.run(storage.list_voices(live.db, 222))) == 1


# ------------------------------------------------------------------------------- RVC

def test_rvc_upload_toggle_restrict_scan_and_delete(app, live):
    page = app.go("rvc")
    page.fill("#new-model-desc", "Caricato dal test")
    page.set_input_files("#new-model-file", file_payload("nuova-voce.zip", zip_bytes({"v.pth": b"p" * 500, "v.index": b"i"})))
    page.get_by_role("button", name="Carica modello").click()
    row = page.get_by_role("row", name="nuova-voce")
    expect(row).to_contain_text("Tutti i server")
    expect(row).to_contain_text("Caricato dal test")

    # interruttore: spegne un modello attivo, il database lo riflette
    switch = page.get_by_role("switch", name="Attiva nuova-voce")
    expect(switch).to_be_checked()
    switch.uncheck()
    expect(page.locator("#toasts")).to_contain_text("Modello disattivato")
    models = {m["name"]: m for m in live.run(storage.list_rvc_models(live.db))}
    assert models["nuova-voce"]["enabled"] is False

    # limita "Hatsune Miku" a un solo server
    page.get_by_role("button", name="Modifica Hatsune Miku").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Tutti i server")).to_be_checked()
    expect(dialog.get_by_label("Ufficio Gaming")).to_be_disabled()
    dialog.get_by_label("Solo alcuni server").check()
    dialog.get_by_label("Ufficio Gaming").check()
    dialog.get_by_role("button", name="Salva").click()
    expect(page.get_by_role("row", name="Hatsune Miku")).to_contain_text("Ufficio Gaming")
    assert live.run(storage.list_rvc_models(live.db, 111, usable_only=True))[0]["name"] != "Hatsune Miku"

    # scansione: una cartella copiata a mano viene trovata
    folder = live.tmp / "models" / "copiato-a-mano"
    folder.mkdir()
    (folder / "x.pth").write_bytes(b"x")
    page.get_by_role("button", name="Cerca nuovi modelli").click()
    expect(page.locator("#toasts")).to_contain_text("Aggiunti: copiato-a-mano")
    expect(page.get_by_role("row", name="copiato-a-mano")).to_be_visible()

    page.get_by_role("button", name="Elimina copiato-a-mano").click()
    page.get_by_role("dialog").get_by_role("button", name="Elimina").click()
    expect(page.get_by_role("row", name="copiato-a-mano")).to_have_count(0)
    assert not folder.exists()


# -------------------------------------------------------------------- sessione e tema

def test_expired_session_sends_you_back_to_the_login(app):
    page = app.go("soundboard")
    app.context.clear_cookies()                                     # la sessione scade/viene invalidata
    page.get_by_role("link", name="Voci clonate").click()
    expect(page.locator("#login-view")).to_be_visible()
    expect(page.locator("#app-view")).to_be_hidden()
    app.login()
    expect(page.locator("#app-view")).to_be_visible()


def test_theme_toggle_is_remembered(app):
    page = app.page
    page.get_by_role("button", name="Cambia tema chiaro/scuro").click()
    first = page.evaluate("document.documentElement.dataset.theme")
    assert first in ("dark", "light")
    page.reload()
    expect(page.locator("#app-view")).to_be_visible()
    assert page.evaluate("document.documentElement.dataset.theme") == first


# -------------------------------------------------------------------- accessibilità

def test_keyboard_and_screen_reader_basics(app):
    page = app.go("soundboard")
    # ogni pulsante e campo ha un nome accessibile
    nameless = page.evaluate("""() => [...document.querySelectorAll('button, input:not([type=file]), select, textarea, a')]
        .filter(el => !el.hidden && el.offsetParent !== null)
        .filter(el => !(el.getAttribute('aria-label') || el.textContent.trim() || (el.labels && el.labels.length)))
        .map(el => el.outerHTML.slice(0, 80))""")
    assert nameless == []
    assert page.evaluate("document.documentElement.lang") == "it"

    # il dialog di conferma: nome accessibile, focus sull'azione sicura, Esc lo chiude
    page.get_by_role("button", name="Elimina Airhorn").click()
    dialog = page.get_by_role("dialog", name="Eliminare il suono?")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="Annulla")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()

    # il link "Vai al contenuto" è il primo elemento raggiungibile con Tab
    page.goto(app.live.url)
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Vai al contenuto")).to_be_focused()


def test_the_page_can_be_driven_by_keyboard_only(make_page):
    p = make_page()
    page = p.page
    expect(page.locator("#login-password")).to_be_focused()        # il cursore è già nel campo password
    page.keyboard.type(PASSWORD)
    page.keyboard.press("Enter")
    expect(page.locator("#app-view")).to_be_visible()


# -------------------------------------------------------------------------- telefono

def test_phone_layout_has_no_sideways_scroll_and_keeps_actions_reachable(make_page):
    p = make_page(viewport={"width": 390, "height": 800}, device_scale_factor=2).logged_in()
    for route in ("panoramica", "soundboard", "voci", "rvc", "server", "registro"):
        page = p.go(route)
        assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0, route
    page = p.go("soundboard")
    edit = page.get_by_role("button", name="Modifica Airhorn")
    box = edit.bounding_box()
    assert box and 0 <= box["x"] and box["x"] + box["width"] <= 390      # il pulsante è dentro lo schermo
    edit.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")


# --------------------------------------------------------------- dati dalla "parte del bot"

def test_changes_made_elsewhere_show_up_after_a_refresh(app, live, tmp_path):
    """Un suono aggiunto dal bot (via storage, altro thread) compare nella dashboard senza riavviarla."""
    page = app.go("soundboard")
    src = tmp_path / "dal-bot.wav"
    src.write_bytes(wav_bytes())
    live.run(storage.add_sound(live.db, 111, "Dal bot", src, actor="bot"))
    page.reload()
    expect(page.get_by_role("row", name="Dal bot")).to_be_visible()
    app.go("registro")
    expect(page.get_by_role("row", name="Suono aggiunto").first).to_contain_text("Dal bot")
    expect(page.get_by_role("row", name="Bot").first).to_be_visible()
