"""Выбор файла или папки для отдельных скриптов без Tk: тот же веб-проводник, что и в приложениях.

Поднимается локальный сервер на 127.0.0.1 (свободный порт), в браузере открывается страница выбора,
функция ждёт ответа и возвращает путь (или None при отмене). Серверная часть — pxg_core/fs_browse.py.

    from pxg_core.pick_dialog import pick_file, pick_files, pick_folder
    path = pick_file("Выберите файл", [("Excel", "*.xlsx *.xls"), ("Все файлы", "*.*")])
"""
from __future__ import annotations

import json
import socket
import threading
import time
import webbrowser
from typing import Any, List, Optional, Sequence, Tuple

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from pxg_core import fs_browse

TIMEOUT = 1800  # секунд ждём выбора, затем считаем отменой

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Выбор</title>
<style>
body{font:14px system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1d2330}
header{padding:12px 16px;background:#fff;border-bottom:1px solid #dde1e8;font-weight:600}
#bar{display:flex;gap:8px;align-items:center;padding:8px 16px;background:#fff}
#path{flex:1;padding:6px 8px;border:1px solid #c9ced8;border-radius:6px}
#places{display:flex;gap:6px;flex-wrap:wrap;padding:0 16px 8px;background:#fff}
#list{margin:8px 16px;background:#fff;border:1px solid #dde1e8;border-radius:6px;height:60vh;overflow:auto}
.row{display:flex;padding:6px 10px;cursor:pointer;border-bottom:1px solid #f0f2f5}
.row:hover,.row.sel{background:#e8f0fe}
.row span.n{flex:1}.row span.s{color:#6b7280;margin-left:12px}
footer{display:flex;gap:8px;justify-content:flex-end;padding:8px 16px}
button{padding:6px 14px;border:1px solid #c9ced8;border-radius:6px;background:#fff;cursor:pointer}
button.primary{background:#1a73e8;color:#fff;border-color:#1a73e8}
button:disabled{opacity:.5;cursor:default}
#err{color:#b42318;padding:0 16px}
</style></head>
<body>
<header id="title"></header>
<div id="bar"><button id="up" title="Вверх">↑</button><input id="path" spellcheck="false"><button id="go">Перейти</button></div>
<div id="places"></div>
<div id="err"></div>
<div id="list"></div>
<footer><button id="cancel">Отмена</button><button id="ok" class="primary" disabled></button></footer>
<script>
const cfg = __CONFIG__;
const $ = id => document.getElementById(id);
let cur = '', marked = null, picked = [], list = null;
const sep = p => (p.includes('\\\\') && !p.includes('/') ? '\\\\' : '/');
const join = (d, n) => d + (d.endsWith('/') || d.endsWith('\\\\') ? '' : sep(d)) + n;
const fmt = n => n < 1024 ? n + ' Б' : n < 1048576 ? (n / 1024).toFixed(0) + ' КБ' : (n / 1048576).toFixed(1) + ' МБ';
const esc = s => s.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
async function api(url, opts) { const r = await fetch(url, opts); return r.json(); }
async function load(path) {
  const q = new URLSearchParams({filter: cfg.filter || '', limit: '2000'});
  if (path) q.set('path', path);
  list = await api('/api/fs/list?' + q);
  if (list.error) { $('err').textContent = list.error; return; }
  $('err').textContent = list.truncated ? 'Показаны первые ' + list.items.length + ' элементов из ' + list.total : '';
  cur = list.path; $('path').value = cur; $('up').disabled = !list.parent;
  marked = null; picked = []; render();
}
function render() {
  const box = $('list');
  box.innerHTML = list.items.map((it, i) => {
    const p = join(cur, it.name);
    const isSel = (marked === p || picked.includes(p)) ? ' sel' : '';
    return '<div class="row' + isSel + '" data-i="' + i + '"><span class="n">' + (it.dir ? '📁 ' : '📄 ') + esc(it.name) +
      '</span>' + (it.dir ? '' : '<span class="s">' + fmt(it.size) + '</span>') + '</div>';
  }).join('');
  box.querySelectorAll('.row').forEach(row => {
    const it = list.items[+row.dataset.i];
    row.onclick = () => {
      if (it.dir) { if (cfg.mode === 'folder') marked = join(cur, it.name); render(); return; }
      if (cfg.mode === 'files') {
        const p = join(cur, it.name); const k = picked.indexOf(p);
        if (k >= 0) picked.splice(k, 1); else picked.push(p);
        render(); return;
      }
      marked = join(cur, it.name); render();
    };
    row.ondblclick = () => {
      if (it.dir) load(join(cur, it.name));
      else choose([join(cur, it.name)]);
    };
  });
  const ok = $('ok');
  if (cfg.mode === 'folder') { ok.textContent = 'Выбрать эту папку'; ok.disabled = false; }
  else if (cfg.mode === 'files') { ok.textContent = 'Выбрать' + (picked.length ? ' (' + picked.length + ')' : ''); ok.disabled = !picked.length; }
  else { ok.textContent = 'Открыть'; ok.disabled = !marked; }
}
async function choose(paths) {
  const dir = cfg.mode === 'folder' ? paths[0] : cur;
  const file = cfg.mode === 'folder' ? '' : paths[0];
  if (dir) await fetch('/api/fs/last', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({dir, file})});
  await fetch('/api/pick/done', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({paths})});
  document.body.innerHTML = '<p style="padding:24px">Готово, можно закрыть вкладку.</p>';
}
$('title').textContent = cfg.title;
$('up').onclick = () => list.parent && load(list.parent);
$('go').onclick = () => load($('path').value);
$('path').onkeydown = e => { if (e.key === 'Enter') load($('path').value); };
$('cancel').onclick = () => choose([]);
$('ok').onclick = () => {
  if (cfg.mode === 'folder') choose([marked || cur]);
  else if (cfg.mode === 'files') choose(picked);
  else choose([marked]);
};
(async () => {
  const places = await api('/api/fs/places');
  $('places').innerHTML = places.places.map(p => '<button data-p="' + esc(p.path) + '">' + esc(p.name) + '</button>').join('');
  $('places').querySelectorAll('button').forEach(b => b.onclick = () => load(b.dataset.p));
  const last = await api('/api/fs/last');
  load(cfg.start || last.dir || '');
})();
</script></body></html>
"""

DIALOG_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Окно</title>
<style>
body{font:15px system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1d2330}
header{padding:12px 16px;background:#fff;border-bottom:1px solid #dde1e8;font-weight:600}
#msg{white-space:pre-line;padding:16px 16px 8px}
#opts{display:flex;flex-direction:column;gap:6px;padding:0 16px}
#opts button{text-align:left;padding:8px 12px}
input{margin:0 16px;padding:6px 8px;border:1px solid #c9ced8;border-radius:6px;width:calc(100% - 32px);box-sizing:border-box}
footer{display:flex;gap:8px;justify-content:flex-end;padding:12px 16px}
button{padding:6px 14px;border:1px solid #c9ced8;border-radius:6px;background:#fff;cursor:pointer}
button.primary{background:#1a73e8;color:#fff;border-color:#1a73e8}
</style></head>
<body>
<header id="title"></header>
<div id="msg"></div>
<div id="body"></div>
<footer id="foot"></footer>
<script>
const cfg = __CONFIG__;
const $ = id => document.getElementById(id);
function send(value) {
  fetch('/api/pick/done', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({value})});
  document.body.innerHTML = '<p style="padding:24px">Готово, можно закрыть вкладку.</p>';
}
function btn(text, cls, fn) { const b = document.createElement('button'); b.textContent = text; if (cls) b.className = cls; b.onclick = fn; return b; }
$('title').textContent = cfg.title;
$('msg').textContent = cfg.message;
const body = $('body'), foot = $('foot');
if (cfg.kind === 'choice') {
  const box = document.createElement('div'); box.id = 'opts';
  cfg.options.forEach(([value, label]) => box.appendChild(btn(label, '', () => send(value))));
  body.appendChild(box);
  foot.appendChild(btn('Отмена', '', () => send(null)));
} else if (cfg.kind === 'text') {
  const input = document.createElement('input'); input.value = cfg.default || '';
  input.onkeydown = e => { if (e.key === 'Enter') send(input.value); };
  body.appendChild(input);
  foot.appendChild(btn('Отмена', '', () => send(null)));
  foot.appendChild(btn('OK', 'primary', () => send(input.value)));
  setTimeout(() => input.focus(), 0);
} else {
  foot.appendChild(btn('OK', 'primary', () => send(null)));
}
</script></body></html>
"""


def make_dialog_app(config: dict, result: dict, done: threading.Event) -> Starlette:
    """Приложение диалога: сообщение, выбор из списка или ввод текста. Ответ — в result['value']."""

    async def page(request: Request) -> HTMLResponse:
        html = DIALOG_PAGE.replace("__CONFIG__", _config_json(config))
        return HTMLResponse(html)

    return Starlette(routes=[Route("/", page), *_answer_routes(result, done), *fs_browse.routes()])


def _config_json(config: dict) -> str:
    # «</» экранируем, чтобы текст сообщения не закрыл тег <script>
    return json.dumps(config, ensure_ascii=False).replace("</", "<\\/")


def _answer_routes(result: dict, done: threading.Event) -> List[Route]:
    async def finish(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        paths = body.get("paths")
        result["paths"] = [str(p) for p in paths] if isinstance(paths, list) and paths else []
        result["value"] = body.get("value")
        done.set()
        return JSONResponse({"ok": True})

    return [Route("/api/pick/done", finish, methods=["POST"])]


def _serve_and_wait(app: Starlette) -> None:
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    started_at = time.monotonic()
    while not server.started and thread.is_alive() and time.monotonic() - started_at < 10:
        time.sleep(0.05)
    try:
        webbrowser.open("http://127.0.0.1:%d/" % port)
        app.state.done.wait(TIMEOUT)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def ask_choice(title: str, message: str, options: Sequence[Tuple[Any, str]]) -> Any:
    """Выбор одного варианта из списка [(значение, подпись), ...]. None — отмена."""
    result: dict = {"value": None}
    done = threading.Event()
    app = make_dialog_app({"kind": "choice", "title": title, "message": message, "options": [list(o) for o in options]},
                          result, done)
    app.state.done = done
    _serve_and_wait(app)
    return result["value"]


def ask_text(title: str, message: str, default: str = "") -> Optional[str]:
    """Ввод строки. None — отмена (как у Tk simpledialog)."""
    result: dict = {"value": None}
    done = threading.Event()
    app = make_dialog_app({"kind": "text", "title": title, "message": message, "default": default}, result, done)
    app.state.done = done
    _serve_and_wait(app)
    return result["value"]


def show_error(title: str, message: str) -> None:
    """Сообщение с кнопкой OK (замена messagebox.showerror)."""
    result: dict = {"value": None}
    done = threading.Event()
    app = make_dialog_app({"kind": "info", "title": title, "message": message}, result, done)
    app.state.done = done
    _serve_and_wait(app)


def _filter_from(filetypes: Optional[Sequence[Tuple[str, str]]]) -> str:
    """Tk-список [(название, '*.xlsx *.xls'), ...] → строка расширений для проводника. «*.*» — все файлы."""
    if not filetypes:
        return ""
    exts: List[str] = []
    for _, pattern in filetypes:
        for item in str(pattern).split():
            if item in ("*", "*.*"):
                return ""
            if item.startswith("*."):
                exts.append(item[2:])
    return " ".join(exts)


def make_app(mode: str, title: str, filt: str, start: str, result: dict, done: threading.Event) -> Starlette:
    """Приложение выбора: страница, настройки для неё и приём ответа. result['paths'] заполняется при ответе."""

    async def page(request: Request) -> HTMLResponse:
        config = {"mode": mode, "title": title, "filter": filt, "start": start}
        html = PAGE.replace("__CONFIG__", _config_json(config))
        return HTMLResponse(html)

    return Starlette(routes=[Route("/", page), *_answer_routes(result, done), *fs_browse.routes()])


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pick(mode: str, title: str, filetypes, start: str) -> List[str]:
    result: dict = {"paths": []}
    done = threading.Event()
    app = make_app(mode, title, _filter_from(filetypes), start or "", result, done)
    app.state.done = done
    _serve_and_wait(app)
    return result["paths"]


def pick_file(title: str = "Выберите файл", filetypes=None, start: str = "") -> str:
    paths = _pick("file", title, filetypes, start)
    return paths[0] if paths else ""


def pick_files(title: str = "Выберите файлы", filetypes=None, start: str = "") -> List[str]:
    return _pick("files", title, filetypes, start)


def pick_folder(title: str = "Выберите папку", start: str = "") -> str:
    paths = _pick("folder", title, None, start)
    return paths[0] if paths else ""
