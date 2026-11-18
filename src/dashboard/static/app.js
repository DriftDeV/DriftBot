/* DriftBot dashboard — JavaScript puro, senza librerie né CDN.
 * Sicurezza: tutto il testo che arriva dal server (nomi dei suoni, dei server...) passa SOLO da
 * createTextNode/setAttribute (helper `h`), mai da innerHTML; niente stili o eventi inline (CSP). */
(() => {
  'use strict';

  const state = { csrf: null, guilds: [], timer: null, player: null, playing: null };

  // ------------------------------------------------------------------ DOM helper
  const $ = (sel, root = document) => root.querySelector(sel);

  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value == null || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else if (value === true) el.setAttribute(key, '');
      else el.setAttribute(key, String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      el.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  function icon(name) {
    const paths = {
      play: 'M8 5v14l11-7z',
      pause: 'M7 5h3v14H7zM14 5h3v14h-3z',
      edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
      trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
      upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
      refresh: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5',
    };
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', paths[name]);
    if (name === 'play' || name === 'pause') path.setAttribute('fill', 'currentColor');
    svg.append(path);
    return svg;
  }

  // -------------------------------------------------------------------- formati
  const nf = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 1 });
  const fmtBytes = (n) => {
    if (!n) return '0 B';
    if (n < 1024) return `${n} B`;
    if (n < 1048576) return `${nf.format(n / 1024)} KB`;
    if (n < 1073741824) return `${nf.format(n / 1048576)} MB`;
    return `${nf.format(n / 1073741824)} GB`;
  };
  const fmtDuration = (s) => {
    if (s == null) return '—';
    const m = Math.floor(s / 60);
    return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`;
  };
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleString('it-IT', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
  const fmtTime = (ts) => new Date(ts * 1000).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'medium' });

  // ------------------------------------------------------------------------ API
  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  function parseBody(text, type) {
    if (type && type.includes('json')) { try { return JSON.parse(text); } catch (e) { return null; } }
    return null;
  }

  async function api(method, path, json) {
    const headers = {};
    if (state.csrf) headers['X-CSRF-Token'] = state.csrf;
    let body;
    if (json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
    let res;
    try {
      res = await fetch(path, { method, headers, body, credentials: 'same-origin' });
    } catch (e) {
      throw new ApiError(0, 'Impossibile contattare il server della dashboard.');
    }
    const data = parseBody(await res.text(), res.headers.get('content-type'));
    if (res.status === 401 && path !== '/api/login') { showLogin(); throw new ApiError(401, 'Sessione scaduta: accedi di nuovo.'); }
    if (!res.ok) throw new ApiError(res.status, (data && data.error) || `Errore ${res.status}`);
    return data;
  }

  function upload(path, form, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', path);
      xhr.setRequestHeader('X-CSRF-Token', state.csrf || '');
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      xhr.onerror = () => reject(new ApiError(0, 'Connessione interrotta durante il caricamento.'));
      xhr.onload = () => {
        const data = parseBody(xhr.responseText, xhr.getResponseHeader('content-type'));
        if (xhr.status === 401) { showLogin(); reject(new ApiError(401, 'Sessione scaduta: accedi di nuovo.')); return; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new ApiError(xhr.status, (data && data.error) || `Errore ${xhr.status}`));
      };
      xhr.send(form);
    });
  }

  // ------------------------------------------------------------ toast e dialog
  function toast(message, kind) {
    const el = h('div', { class: `toast ${kind === 'error' ? 'is-error' : 'is-ok'}` }, message);
    $('#toasts').append(el);
    setTimeout(() => el.remove(), kind === 'error' ? 8000 : 4500);
  }
  const fail = (e) => toast(e instanceof ApiError ? e.message : 'Errore imprevisto.', 'error');

  function openDialog(build) {
    return new Promise((resolve) => {
      const dialog = $('#dialog');
      dialog.replaceChildren();
      const close = (value) => { dialog.close(); resolve(value); };
      dialog.append(build(close));
      dialog.addEventListener('close', () => resolve(undefined), { once: true });
      dialog.showModal();
    });
  }

  function confirmDialog({ title, message, confirmLabel, danger }) {
    return openDialog((close) => {
      const cancel = h('button', { class: 'btn', type: 'button', onclick: () => close(false) }, 'Annulla');
      const ok = h('button', { class: `btn ${danger ? 'btn-danger solid' : 'btn-primary'}`, type: 'button', onclick: () => close(true) }, confirmLabel || 'Conferma');
      const box = h('div', { role: 'document' },
        h('h2', { id: 'dlg-title' }, title), h('p', null, message),
        h('div', { class: 'dialog-actions' }, cancel, ok));
      $('#dialog').setAttribute('aria-labelledby', 'dlg-title');
      queueMicrotask(() => cancel.focus());          // l'azione sicura ha il focus
      return box;
    }).then((v) => v === true);
  }

  // --------------------------------------------------------------- componenti
  const guildName = (id) => {
    if (id === 0) return 'Globale';
    const g = state.guilds.find((x) => x.id === id);
    return g ? g.name : `Server ${id}`;
  };

  async function loadGuilds() {
    try { state.guilds = (await api('GET', '/api/guilds')).guilds; } catch (e) { if (e.status !== 401) fail(e); }
  }

  function scopeBadge(id) {
    return id === 0 ? h('span', { class: 'badge badge-info' }, '🌐 Globale') : h('span', { class: 'badge' }, guildName(id));
  }

  function scopeSelect({ id, label, value, withAll, withGlobal, onchange }) {
    const select = h('select', { id, onchange });
    if (withAll) select.append(h('option', { value: 'all' }, 'Tutti i server'));
    if (withGlobal) select.append(h('option', { value: 'global' }, '🌐 Globale (tutti i server)'));
    for (const g of state.guilds) select.append(h('option', { value: String(g.id) }, g.present ? g.name : `${g.name} (non presente)`));
    select.value = String(value);
    if (select.value !== String(value)) select.selectedIndex = 0;
    return h('div', { class: 'field' }, h('label', { for: id }, label), select);
  }

  /* Aggiunge data-label alle celle (usato dal layout a schede sul telefono). */
  function responsiveTable(wrap) {
    const table = $('table', wrap);
    const heads = [...table.querySelectorAll('thead th')].map((th) => (th.querySelector('.visually-hidden') ? '' : th.textContent.trim()));
    table.querySelectorAll('tbody tr').forEach((tr) => [...tr.children].forEach((td, i) => { if (heads[i]) td.dataset.label = heads[i]; }));
    return wrap;
  }

  function emptyState(title, text) {
    return h('div', { class: 'empty' }, h('h3', null, title), h('p', null, text));
  }

  function setBusy(button, busy, label) {
    button.disabled = busy;
    if (label) button.textContent = busy ? label.busy : label.idle;
  }

  /* Campo "file" con trascinamento. Restituisce { el, input, onpick } */
  function fileField({ id, accept, label, hint }) {
    const input = h('input', { id, type: 'file', accept, class: 'visually-hidden', required: true });
    const nameEl = h('span', { class: 'file-name' }, 'Nessun file scelto');
    const zone = h('label', { class: 'dropzone', for: id },
      h('strong', null, label), h('span', null, 'Clicca per scegliere o trascina qui il file'), nameEl);
    const picked = [];
    input.addEventListener('change', () => {
      const file = input.files[0];
      nameEl.textContent = file ? file.name : 'Nessun file scelto';
      picked.forEach((fn) => fn(file));
    });
    for (const ev of ['dragenter', 'dragover']) zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('is-over'); });
    for (const ev of ['dragleave', 'drop']) zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('is-over'); });
    zone.addEventListener('drop', (e) => {
      if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event('change')); }
    });
    return { el: h('div', { class: 'field' }, input, zone, hint ? h('span', { class: 'hint' }, hint) : null), input, onpick: (fn) => picked.push(fn) };
  }

  const stem = (filename) => filename.replace(/\.[^.]+$/, '');

  /* Propone come nome quello del file scelto, ma solo se l'utente non ha scritto un nome suo. */
  function suggestName(file, name) {
    let last = '';
    file.onpick((f) => {
      if (!f) return;
      if (name.input.value === '' || name.input.value === last) {
        last = stem(f.name).slice(0, 100);
        name.input.value = last;
      }
    });
  }

  /* Modulo di caricamento generico: costruisce FormData, mostra la barra di avanzamento. */
  function uploadCard({ title, intro, path, fields, file, submitLabel, onDone }) {
    const progress = h('progress', { max: '1', value: '0', hidden: true, 'aria-label': 'Avanzamento del caricamento' });
    const status = h('p', { class: 'hint', role: 'status' });
    const button = h('button', { class: 'btn btn-primary', type: 'submit' }, icon('upload'), submitLabel);
    const form = h('form', { novalidate: false },
      h('div', { class: 'form-row' }, fields.map((f) => f.el)), file.el, progress, status,
      h('div', { class: 'dialog-actions' }, button));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = new FormData();
      for (const f of fields) f.append(data);
      data.append('file', file.input.files[0]);
      button.disabled = true; progress.hidden = false; progress.value = 0; status.textContent = 'Caricamento in corso…';
      try {
        const result = await upload(path, data, (p) => { progress.value = p; });
        toast('Caricato con successo.', 'ok');
        form.reset(); file.input.dispatchEvent(new Event('change'));
        status.textContent = '';
        await onDone(result);
      } catch (err) {
        status.textContent = '';
        fail(err);
      } finally {
        button.disabled = false; progress.hidden = true;
      }
    });
    return h('section', { class: 'card', 'aria-labelledby': `${path.replace(/\W/g, '')}-h` },
      h('h2', { id: `${path.replace(/\W/g, '')}-h` }, title), intro ? h('p', { class: 'muted' }, intro) : null, form);
  }

  function textField({ id, name, label, hint, required, maxlength, value }) {
    const input = h('input', { id, type: 'text', maxlength: maxlength || 100, required, autocomplete: 'off', value: value || '' });
    return {
      el: h('div', { class: 'field' }, h('label', { for: id }, label), input, hint ? h('span', { class: 'hint' }, hint) : null),
      input, append: (fd) => fd.append(name, input.value),
    };
  }

  function selectField({ id, name, label, hint, build }) {
    const wrap = build();
    const select = $('select', wrap);
    select.id = id;
    $('label', wrap).setAttribute('for', id);
    $('label', wrap).textContent = label;
    if (hint) wrap.append(h('span', { class: 'hint' }, hint));
    return { el: wrap, select, append: (fd) => fd.append(name, select.value) };
  }

  // ------------------------------------------------------------------ player
  function togglePlay(button, url) {
    if (!state.player) {
      state.player = new Audio();
      state.player.addEventListener('ended', () => resetPlayButton());
      state.player.addEventListener('error', () => { resetPlayButton(); toast('Impossibile riprodurre il file.', 'error'); });
    }
    const same = state.playing && state.playing.url === url;
    resetPlayButton();
    if (same) { state.player.pause(); return; }
    state.player.src = url;
    state.player.play().catch(() => {});
    state.playing = { url, button };
    button.replaceChildren(icon('pause'));
    button.setAttribute('aria-pressed', 'true');
  }

  function resetPlayButton() {
    if (state.player) state.player.pause();
    if (state.playing) {
      state.playing.button.replaceChildren(icon('play'));
      state.playing.button.setAttribute('aria-pressed', 'false');
    }
    state.playing = null;
  }

  function playButton(url, name) {
    const button = h('button', { class: 'btn btn-ghost btn-icon', type: 'button', 'aria-label': `Ascolta ${name}`, title: 'Ascolta', 'aria-pressed': 'false' }, icon('play'));
    button.addEventListener('click', () => togglePlay(button, url));
    return button;
  }

  const iconButton = (name, label, onclick, extra) =>
    h('button', { class: `btn btn-ghost btn-icon ${extra || ''}`, type: 'button', 'aria-label': label, title: label, onclick }, icon(name));

  // ------------------------------------------------------------------- viste
  const views = {};
  const routeParams = () => new URLSearchParams((location.hash.split('?')[1] || ''));
  const routeName = () => (location.hash.replace(/^#\//, '').split('?')[0] || 'panoramica');

  function pageHead(title, text, ...actions) {
    return h('div', { class: 'page-head' }, h('div', null, h('h1', null, title), text ? h('p', null, text) : null), h('div', null, actions));
  }

  // -- Panoramica
  views.panoramica = async (main, signal) => {
    const body = h('div', { class: 'stack' });
    main.append(pageHead('Panoramica', 'Stato del bot e del database. Si aggiorna da solo ogni pochi secondi.'), body);

    async function draw() {
      const data = await api('GET', '/api/overview');
      if (signal.aborted) return;
      const c = data.counts, db = data.db;
      const stat = (label, value) => h('div', { class: 'card stat' }, h('div', { class: 'stat-value' }, String(value)), h('div', { class: 'stat-label' }, label));
      body.replaceChildren(
        h('div', { class: 'grid' },
          stat('Server', c.guilds), stat('Suoni dei server', c.sounds), stat('Suoni globali', c.global_sounds),
          stat('Voci clonate', c.voices), stat('Modelli RVC attivi / totali', `${c.rvc_enabled}/${c.rvc_models}`), stat('Spazio occupato', fmtBytes(c.disk_bytes))),
        h('div', { class: 'grid grid-wide' },
          h('section', { class: 'card', 'aria-labelledby': 'bot-h' },
            h('h2', { id: 'bot-h' }, 'Bot'),
            h('dl', { class: 'kv' },
              h('dt', null, 'Connessione'), h('dd', null, data.bot.connected ? 'Online' : 'Non connesso'),
              h('dt', null, 'Account'), h('dd', null, data.bot.user || '—'),
              h('dt', null, 'Latenza'), h('dd', null, data.bot.latency_ms != null ? `${data.bot.latency_ms} ms` : '—'))),
          h('section', { class: 'card', 'aria-labelledby': 'db-h' },
            h('h2', { id: 'db-h' }, 'Database'),
            h('dl', { class: 'kv' },
              h('dt', null, 'Modalità'), h('dd', null, db.journal_mode.toUpperCase()),
              h('dt', null, 'Dimensione'), h('dd', null, fmtBytes(db.size_bytes)),
              h('dt', null, 'Giornale (WAL)'), h('dd', null, fmtBytes(db.wal_bytes)),
              h('dt', null, 'Scritture in coda'), h('dd', null, String(db.queue_depth)),
              h('dt', null, 'Scritture riuscite'), h('dd', null, String(db.writes_done)),
              h('dt', null, 'Scritture fallite'), h('dd', null, String(db.writes_failed)),
              h('dt', null, 'Gruppi (commit)'), h('dd', null, String(db.batches)),
              h('dt', null, 'Gruppo più grande'), h('dd', null, String(db.max_batch))),
            db.last_error ? h('p', { class: 'form-error' }, `Ultimo errore: ${db.last_error}`) : null)),
        h('p', { class: 'note' }, 'Le modifiche fatte da qui e dai comandi del bot passano da una coda di scrittura: più persone possono caricare o modificare contemporaneamente senza conflitti.'));
    }

    await draw();
    state.timer = setInterval(() => { if (!document.hidden) draw().catch(() => {}); }, 5000);
  };

  // -- Soundboard
  views.soundboard = async (main) => {
    await loadGuilds();
    const scope = routeParams().get('scope') || 'all';
    const list = h('div', null, h('p', { class: 'loading' }, 'Caricamento…'));
    const filter = scopeSelect({
      id: 'sound-scope', label: 'Mostra', value: scope, withAll: true, withGlobal: true,
      onchange: (e) => { location.hash = `#/soundboard?scope=${e.target.value}`; },
    });

    async function draw() {
      const data = await api('GET', `/api/sounds?scope=${encodeURIComponent(scope)}`);
      if (!data.sounds.length) { list.replaceChildren(emptyState('Nessun suono', 'Carica il primo con il modulo qui sotto.')); return; }
      list.replaceChildren(responsiveTable(h('div', { class: 'table-wrap' }, h('table', null,
        h('caption', null, plural(data.sounds.length, 'suono', 'suoni')),
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Ascolta')),
          h('th', { scope: 'col' }, 'Nome'), h('th', { scope: 'col' }, 'Dove'), h('th', { scope: 'col' }, 'Formato'),
          h('th', { scope: 'col', class: 'num' }, 'Dimensione'), h('th', { scope: 'col' }, 'Aggiunto'),
          h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Azioni')))),
        h('tbody', null, data.sounds.map((s) => h('tr', null,
          h('td', null, s.missing ? null : playButton(`/api/sounds/${s.id}/audio`, s.name)),
          h('td', { class: 'cell-name' }, s.name, s.missing ? [' ', h('span', { class: 'badge badge-warn', title: 'Il file non esiste più sul disco' }, 'File mancante')] : null),
          h('td', null, scopeBadge(s.guild_id)), h('td', null, s.format.toUpperCase()),
          h('td', { class: 'num nowrap' }, fmtBytes(s.size)), h('td', { class: 'nowrap' }, fmtDate(s.created_at)),
          h('td', { class: 'actions' },
            iconButton('edit', `Modifica ${s.name}`, () => editSound(s)),
            iconButton('trash', `Elimina ${s.name}`, () => deleteSound(s), 'btn-danger-ghost')))))))));
    }

    async function editSound(s) {
      const result = await openDialog((close) => {
        const name = textField({ id: 'edit-name', name: 'name', label: 'Nome', required: true, value: s.name });
        const where = scopeSelect({ id: 'edit-scope', label: 'Dove è disponibile', value: s.guild_id === 0 ? 'global' : s.guild_id, withGlobal: true });
        const err = h('p', { class: 'form-error', role: 'alert', hidden: true });
        const form = h('form', { method: 'dialog' }, h('h2', { id: 'dlg-title' }, 'Modifica suono'), name.el, where, err,
          h('div', { class: 'dialog-actions' },
            h('button', { class: 'btn', type: 'button', onclick: () => close(undefined) }, 'Annulla'),
            h('button', { class: 'btn btn-primary', type: 'submit' }, 'Salva')));
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          try {
            const scopeValue = $('select', where).value;
            const body = { name: name.input.value };
            if (scopeValue !== (s.guild_id === 0 ? 'global' : String(s.guild_id))) body.scope = scopeValue;
            await api('PATCH', `/api/sounds/${s.id}`, body);
            close(true);
          } catch (e2) { err.textContent = e2.message; err.hidden = false; }
        });
        $('#dialog').setAttribute('aria-labelledby', 'dlg-title');
        queueMicrotask(() => name.input.select());
        return form;
      });
      if (result) { toast('Suono aggiornato.', 'ok'); await refresh(); }
    }

    async function deleteSound(s) {
      if (!(await confirmDialog({ title: 'Eliminare il suono?', message: `«${s.name}» verrà eliminato per sempre, file compreso.`, confirmLabel: 'Elimina', danger: true }))) return;
      try { await api('DELETE', `/api/sounds/${s.id}`); toast('Suono eliminato.', 'ok'); await refresh(); } catch (e) { fail(e); }
    }

    const refresh = async () => { await loadGuilds(); await draw(); };

    const name = textField({ id: 'new-sound-name', name: 'name', label: 'Nome del suono', hint: 'Se lo lasci vuoto si usa il nome del file.' });
    const where = selectField({
      id: 'new-sound-scope', name: 'scope', label: 'Dove è disponibile',
      build: () => scopeSelect({ id: 'x', label: 'x', value: scope === 'all' ? 'global' : scope, withGlobal: true }),
      hint: 'Globale = usabile in tutti i server.',
    });
    const file = fileField({ id: 'new-sound-file', accept: 'audio/*,.wav,.mp3,.ogg,.flac,.m4a', label: 'File audio', hint: 'WAV, MP3, OGG, FLAC o M4A.' });
    suggestName(file, name);

    main.append(
      pageHead('Soundboard', 'I suoni che si riproducono con /soundboard. I suoni globali sono disponibili in tutti i server.'),
      h('div', { class: 'toolbar' }, filter),
      list,
      h('div', { class: 'stack' }, uploadCard({ title: 'Aggiungi un suono', path: '/api/sounds', fields: [name, where], file, submitLabel: 'Carica suono', onDone: refresh })));
    await draw();
  };

  // -- Voci clonate
  views.voci = async (main) => {
    await loadGuilds();
    const scope = routeParams().get('guild') || 'all';
    const list = h('div', null, h('p', { class: 'loading' }, 'Caricamento…'));
    const filter = scopeSelect({
      id: 'voice-scope', label: 'Mostra', value: scope, withAll: true,
      onchange: (e) => { location.hash = `#/voci?guild=${e.target.value}`; },
    });

    async function draw() {
      const data = await api('GET', `/api/voices?guild=${encodeURIComponent(scope)}`);
      if (!data.voices.length) { list.replaceChildren(emptyState('Nessuna voce clonata', 'Si creano con /new-speaker nel bot, oppure caricando un campione qui sotto.')); return; }
      list.replaceChildren(responsiveTable(h('div', { class: 'table-wrap' }, h('table', null,
        h('caption', null, plural(data.voices.length, 'voce', 'voci')),
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Ascolta')),
          h('th', { scope: 'col' }, 'Nome'), h('th', { scope: 'col' }, 'Server'), h('th', { scope: 'col', class: 'num' }, 'Durata'),
          h('th', { scope: 'col' }, 'Formato'), h('th', { scope: 'col', class: 'num' }, 'Dimensione'), h('th', { scope: 'col' }, 'Aggiunta'),
          h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Azioni')))),
        h('tbody', null, data.voices.map((v) => h('tr', null,
          h('td', null, v.missing ? null : playButton(`/api/voices/${v.id}/audio`, v.name)),
          h('td', { class: 'cell-name' }, v.name, v.missing ? [' ', h('span', { class: 'badge badge-warn' }, 'File mancante')] : null),
          h('td', null, scopeBadge(v.guild_id)), h('td', { class: 'num' }, fmtDuration(v.duration)), h('td', null, v.format.toUpperCase()),
          h('td', { class: 'num nowrap' }, fmtBytes(v.size)), h('td', { class: 'nowrap' }, fmtDate(v.created_at)),
          h('td', { class: 'actions' },
            iconButton('edit', `Rinomina ${v.name}`, () => renameVoice(v)),
            iconButton('trash', `Elimina ${v.name}`, () => deleteVoice(v))))))))));
    }

    async function renameVoice(v) {
      const result = await openDialog((close) => {
        const name = textField({ id: 'edit-voice', name: 'name', label: 'Nome della voce', required: true, value: v.name });
        const err = h('p', { class: 'form-error', role: 'alert', hidden: true });
        const form = h('form', { method: 'dialog' }, h('h2', { id: 'dlg-title' }, 'Rinomina voce'), name.el, err,
          h('div', { class: 'dialog-actions' },
            h('button', { class: 'btn', type: 'button', onclick: () => close(undefined) }, 'Annulla'),
            h('button', { class: 'btn btn-primary', type: 'submit' }, 'Salva')));
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          try { await api('PATCH', `/api/voices/${v.id}`, { name: name.input.value }); close(true); } catch (e2) { err.textContent = e2.message; err.hidden = false; }
        });
        $('#dialog').setAttribute('aria-labelledby', 'dlg-title');
        queueMicrotask(() => name.input.select());
        return form;
      });
      if (result) { toast('Voce rinominata.', 'ok'); await refresh(); }
    }

    async function deleteVoice(v) {
      if (!(await confirmDialog({ title: 'Eliminare la voce?', message: `«${v.name}» (${guildName(v.guild_id)}) verrà eliminata per sempre, campione compreso.`, confirmLabel: 'Elimina', danger: true }))) return;
      try { await api('DELETE', `/api/voices/${v.id}`); toast('Voce eliminata.', 'ok'); await refresh(); } catch (e) { fail(e); }
    }

    const refresh = async () => { await loadGuilds(); await draw(); };

    const name = textField({ id: 'new-voice-name', name: 'name', label: 'Nome della voce', hint: 'Se lo lasci vuoto si usa il nome del file.' });
    const where = selectField({
      id: 'new-voice-guild', name: 'guild', label: 'Server',
      build: () => scopeSelect({ id: 'x', label: 'x', value: scope === 'all' ? (state.guilds[0] ? state.guilds[0].id : '') : scope }),
      hint: 'Ogni voce appartiene a un server.',
    });
    const file = fileField({ id: 'new-voice-file', accept: 'audio/*,.wav,.mp3,.ogg,.flac,.m4a', label: 'Campione della voce', hint: 'Almeno 10 secondi di voce pulita, senza musica di sottofondo.' });
    suggestName(file, name);

    main.append(
      pageHead('Voci clonate', 'Le voci usate da /tts-ai. Ogni server ha le sue.'),
      h('div', { class: 'toolbar' }, filter), list,
      state.guilds.length
        ? uploadCard({ title: 'Aggiungi una voce', path: '/api/voices', fields: [name, where], file, submitLabel: 'Carica voce', onDone: refresh })
        : h('p', { class: 'note' }, 'Il bot non è ancora entrato in nessun server: non si possono aggiungere voci.'));
    await draw();
  };

  // -- Modelli RVC
  views.rvc = async (main) => {
    await loadGuilds();
    const list = h('div', null, h('p', { class: 'loading' }, 'Caricamento…'));

    async function draw() {
      const data = await api('GET', '/api/rvc');
      if (!data.models.length) { list.replaceChildren(emptyState('Nessun modello', 'Carica uno zip con il file .pth (ed eventualmente .index) oppure copia la cartella in models/ e usa «Cerca nuovi modelli».')); return; }
      list.replaceChildren(responsiveTable(h('div', { class: 'table-wrap' }, h('table', null,
        h('caption', null, plural(data.models.length, 'modello', 'modelli')),
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Attivo'), h('th', { scope: 'col' }, 'Nome'),
          h('th', { scope: 'col' }, 'Disponibile in'), h('th', { scope: 'col', class: 'num' }, 'Dimensione'),
          h('th', { scope: 'col' }, 'Aggiunto'), h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Azioni')))),
        h('tbody', null, data.models.map((m) => {
          const toggle = h('input', { type: 'checkbox', role: 'switch', 'aria-label': `Attiva ${m.name}` });
          toggle.checked = m.enabled;
          toggle.addEventListener('change', async () => {
            try { await api('PATCH', `/api/rvc/${m.id}`, { enabled: toggle.checked }); toast(toggle.checked ? 'Modello attivato.' : 'Modello disattivato.', 'ok'); }
            catch (e) { toggle.checked = !toggle.checked; fail(e); }
          });
          const available = m.guild_ids.length
            ? m.guild_ids.map((id) => h('span', { class: 'badge' }, guildName(id)))
            : [h('span', { class: 'badge badge-ok' }, 'Tutti i server')];
          return h('tr', null,
            h('td', null, h('label', { class: 'switch' }, toggle, h('span', { class: 'track' }))),
            h('td', { class: 'cell-name' }, m.name, m.missing ? [' ', h('span', { class: 'badge badge-warn', title: 'La cartella del modello non esiste più' }, 'Cartella mancante')] : null,
              m.description ? h('div', { class: 'hint' }, m.description) : null),
            h('td', null, available.flatMap((b, i) => [i ? ' ' : null, b])),
            h('td', { class: 'num nowrap' }, fmtBytes(m.size)), h('td', { class: 'nowrap' }, fmtDate(m.created_at)),
            h('td', { class: 'actions' },
              iconButton('edit', `Modifica ${m.name}`, () => editModel(m)),
              iconButton('trash', `Elimina ${m.name}`, () => deleteModel(m))));
        }))))));
    }

    function guildChecklist(selected) {
      const mode = (value, label, checked) => h('label', { class: 'choice' },
        h('input', { type: 'radio', name: 'access-mode', value, checked }), label);
      const all = mode('all', 'Tutti i server', selected.length === 0);
      const some = mode('some', 'Solo alcuni server', selected.length > 0);
      const boxes = state.guilds.map((g) => {
        const input = h('input', { type: 'checkbox', value: String(g.id), checked: selected.includes(g.id) });
        return h('label', { class: 'choice' }, input, g.name);
      });
      const checks = h('div', { class: 'checks' }, boxes.length ? boxes : h('span', { class: 'hint' }, 'Nessun server noto.'));
      const fieldset = h('fieldset', null, h('legend', null, 'Disponibile in'), all, some, checks);
      const sync = () => { const only = $('input[value="some"]', fieldset).checked; checks.querySelectorAll('input').forEach((i) => { i.disabled = !only; }); };
      fieldset.addEventListener('change', sync); sync();
      return { el: fieldset, value: () => ($('input[value="some"]', fieldset).checked ? [...checks.querySelectorAll('input:checked')].map((i) => Number(i.value)) : []) };
    }

    async function editModel(m) {
      const result = await openDialog((close) => {
        const name = textField({ id: 'edit-model-name', name: 'name', label: 'Nome', required: true, value: m.name });
        const desc = h('textarea', { id: 'edit-model-desc', maxlength: '500' }); desc.value = m.description;
        const access = guildChecklist(m.guild_ids);
        const err = h('p', { class: 'form-error', role: 'alert', hidden: true });
        const form = h('form', { method: 'dialog' }, h('h2', { id: 'dlg-title' }, 'Modifica modello'), name.el,
          h('div', { class: 'field' }, h('label', { for: 'edit-model-desc' }, 'Descrizione'), desc), access.el, err,
          h('div', { class: 'dialog-actions' },
            h('button', { class: 'btn', type: 'button', onclick: () => close(undefined) }, 'Annulla'),
            h('button', { class: 'btn btn-primary', type: 'submit' }, 'Salva')));
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          try {
            await api('PATCH', `/api/rvc/${m.id}`, { name: name.input.value, description: desc.value, guild_ids: access.value() });
            close(true);
          } catch (e2) { err.textContent = e2.message; err.hidden = false; }
        });
        $('#dialog').setAttribute('aria-labelledby', 'dlg-title');
        queueMicrotask(() => name.input.select());
        return form;
      });
      if (result) { toast('Modello aggiornato.', 'ok'); await draw(); }
    }

    async function deleteModel(m) {
      if (!(await confirmDialog({ title: 'Eliminare il modello?', message: `«${m.name}» e i suoi file verranno eliminati per sempre.`, confirmLabel: 'Elimina', danger: true }))) return;
      try { await api('DELETE', `/api/rvc/${m.id}`); toast('Modello eliminato.', 'ok'); await draw(); } catch (e) { fail(e); }
    }

    const scanButton = h('button', { class: 'btn', type: 'button' }, icon('refresh'), 'Cerca nuovi modelli');
    scanButton.addEventListener('click', async () => {
      scanButton.disabled = true;
      try {
        const r = await api('POST', '/api/rvc/scan');
        toast(r.added.length ? `Aggiunti: ${r.added.join(', ')}` : 'Nessun nuovo modello trovato.', 'ok');
        if (r.missing.length) toast(`Cartella mancante per: ${r.missing.join(', ')}`, 'error');
        await draw();
      } catch (e) { fail(e); } finally { scanButton.disabled = false; }
    });

    const name = textField({ id: 'new-model-name', name: 'name', label: 'Nome del modello', hint: 'Se lo lasci vuoto si usa il nome del file.' });
    const desc = textField({ id: 'new-model-desc', name: 'description', label: 'Descrizione (facoltativa)', maxlength: 500 });
    const file = fileField({ id: 'new-model-file', accept: '.zip,.pth', label: 'Modello RVC', hint: 'Uno .zip con il file .pth (ed eventualmente .index) oppure un singolo .pth.' });
    suggestName(file, name);

    main.append(
      pageHead('Modelli RVC', 'Le voci disponibili per /ai-cover. Puoi limitare un modello a certi server o spegnerlo senza eliminarlo.', scanButton),
      list,
      h('div', { class: 'stack' }, uploadCard({ title: 'Aggiungi un modello', intro: 'Dopo il caricamento il modello è subito disponibile in tutti i server: usa «Modifica» per limitarlo.', path: '/api/rvc', fields: [name, desc], file, submitLabel: 'Carica modello', onDone: draw })));
    await draw();
  };

  // -- Server
  views.server = async (main) => {
    await loadGuilds();
    if (!state.guilds.length) { main.append(pageHead('Server'), emptyState('Nessun server', 'Il bot non è ancora entrato in nessun server.')); return; }
    main.append(pageHead('Server', 'I server in cui il bot è (o è stato) presente e cosa hanno salvato.'),
      h('div', { class: 'grid grid-wide' }, state.guilds.map((g) => {
        const iconUrl = g.icon_url && /^https:\/\/cdn\.discordapp\.com\//.test(g.icon_url) ? g.icon_url : null;
        const initials = g.name.split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase();
        return h('article', { class: 'card', 'aria-label': g.name },
          h('div', { class: 'guild' },
            iconUrl ? h('img', { class: 'guild-icon', src: iconUrl, alt: '', width: '48', height: '48', referrerpolicy: 'no-referrer' }) : h('div', { class: 'guild-icon', 'aria-hidden': 'true' }, initials),
            h('div', null, h('h3', null, g.name),
              h('div', { class: 'muted small' }, g.member_count != null ? `${g.member_count} membri` : 'Membri sconosciuti'))),
          h('div', { class: 'guild-stats' },
            h('span', { class: `badge ${g.present ? 'badge-ok' : 'badge-warn'}` }, g.present ? 'Presente' : 'Non presente'),
            h('a', { class: 'badge badge-info', href: `#/soundboard?scope=${g.id}` }, plural(g.sounds, 'suono', 'suoni')),
            h('a', { class: 'badge badge-info', href: `#/voci?guild=${g.id}` }, plural(g.voices, 'voce', 'voci'))));
      })));
  };

  // -- Registro
  const ACTIONS = {
    login: 'Accesso', 'sound.add': 'Suono aggiunto', 'sound.rename': 'Suono rinominato', 'sound.move': 'Suono spostato',
    'sound.delete': 'Suono eliminato', 'voice.add': 'Voce aggiunta', 'voice.replace': 'Voce sostituita',
    'voice.rename': 'Voce rinominata', 'voice.delete': 'Voce eliminata', 'rvc.add': 'Modello RVC aggiunto',
    'rvc.update': 'Modello RVC modificato', 'rvc.delete': 'Modello RVC eliminato', 'rvc.scan': 'Scansione modelli RVC',
    'legacy.import': 'Import dai vecchi file JSON',
  };
  const ACTORS = { dashboard: 'Dashboard', bot: 'Bot', import: 'Importazione' };

  views.registro = async (main) => {
    const data = await api('GET', '/api/audit?limit=200');
    main.append(pageHead('Registro', 'Le ultime modifiche a suoni, voci e modelli: chi le ha fatte e quando.'));
    if (!data.entries.length) { main.append(emptyState('Ancora nulla', 'Le modifiche compariranno qui.')); return; }
    main.append(responsiveTable(h('div', { class: 'table-wrap' }, h('table', null,
      h('caption', null, `Ultime ${data.entries.length} operazioni`),
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Quando'), h('th', { scope: 'col' }, 'Da'), h('th', { scope: 'col' }, 'Azione'), h('th', { scope: 'col' }, 'Dettaglio'))),
      h('tbody', null, data.entries.map((e) => h('tr', null,
        h('td', { class: 'nowrap' }, fmtTime(e.ts)),
        h('td', null, ACTORS[e.actor] || (e.actor.startsWith('discord:') ? `Utente Discord ${e.actor.slice(8)}` : e.actor)),
        h('td', null, ACTIONS[e.action] || e.action), h('td', { class: 'cell-name' }, e.detail))))))));
  };

  // ------------------------------------------------------------- navigazione
  async function render() {
    if (!state.csrf) return;
    clearInterval(state.timer);
    resetPlayButton();
    const controller = new AbortController();
    render.controller && render.controller.abort();
    render.controller = controller;
    const name = views[routeName()] ? routeName() : 'panoramica';
    document.querySelectorAll('#nav a').forEach((a) => {
      if (a.dataset.route === name) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const main = $('#main');
    main.replaceChildren(h('p', { class: 'loading' }, 'Caricamento…'));
    const fresh = h('div');
    try {
      await views[name](fresh, controller.signal);
      if (controller.signal.aborted) return;
      main.replaceChildren(...fresh.childNodes);
    } catch (e) {
      if (controller.signal.aborted || e.status === 401) return;
      main.replaceChildren(emptyState('Qualcosa è andato storto', e.message || 'Errore imprevisto.'));
    }
    document.title = `${$(`#nav a[data-route="${name}"]`).textContent} · DriftBot`;
  }

  async function refreshStatus() {
    try {
      const data = await api('GET', '/api/overview');
      const pill = $('#bot-status');
      pill.textContent = data.bot.connected ? `Online${data.bot.latency_ms != null ? ` · ${data.bot.latency_ms} ms` : ''}` : 'Offline';
      pill.className = `pill ${data.bot.connected ? 'is-ok' : 'is-bad'}`;
    } catch (e) { /* lo stato si riprova al prossimo giro */ }
  }

  function showLogin() {
    state.csrf = null;
    clearInterval(state.timer);
    clearInterval(showLogin.status);
    $('#app-view').hidden = true;
    $('#login-view').hidden = false;
    $('#login-password').value = '';
    $('#login-password').focus();
  }

  function startApp(moveFocus) {
    $('#login-view').hidden = true;
    $('#app-view').hidden = false;
    refreshStatus();
    clearInterval(showLogin.status);
    showLogin.status = setInterval(() => { if (!document.hidden && state.csrf) refreshStatus(); }, 15000);
    if (!location.hash) location.hash = '#/panoramica'; else render();
    // Dopo un accesso il focus passa al contenuto; ricaricando la pagina non si ruba il focus (il primo Tab resta «Vai al contenuto»)
    if (moveFocus) $('#main').focus({ preventScroll: true });
  }

  // ------------------------------------------------------------------ avvio
  function applyTheme(theme) {
    if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
  }
  try { applyTheme(localStorage.getItem('theme')); } catch (e) { /* archiviazione non disponibile */ }

  $('#theme-toggle').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    const next = dark ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('theme', next); } catch (e) { /* ignora */ }
  });

  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const error = $('#login-error');
    error.hidden = true;
    const button = $('button[type="submit"]', e.target);
    button.disabled = true;
    try {
      const data = await api('POST', '/api/login', { password: $('#login-password').value });
      state.csrf = data.csrf;
      startApp(true);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      $('#login-password').select();
    } finally { button.disabled = false; }
  });

  $('#logout').addEventListener('click', async () => {
    try { await api('POST', '/api/logout'); } catch (e) { /* già scaduta */ }
    showLogin();
  });

  window.addEventListener('hashchange', render);

  (async () => {
    try {
      const res = await fetch('/api/session', { credentials: 'same-origin' });
      const data = await res.json();
      if (data.authenticated) { state.csrf = data.csrf; startApp(); } else showLogin();
    } catch (e) { showLogin(); }
  })();
})();
