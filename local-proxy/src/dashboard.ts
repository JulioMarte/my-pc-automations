// Panel de estado del gateway: HTML autonomo (sin build ni dependencias) servido
// en GET /panel. No incrusta secretos: el STATS_TOKEN lo escribe el operador y se
// guarda en localStorage del navegador. Pensado para verse desde el movil dentro
// de la tailnet.
export function renderDashboard(): string {
  return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>local-proxy</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.4 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f1115; color: #e6e8eb; padding: 16px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #8b93a1; font-size: 12px; margin-bottom: 16px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
  input, button { font: inherit; border-radius: 8px; border: 1px solid #2a2f3a;
                  background: #171a21; color: #e6e8eb; padding: 8px 10px; }
  input { flex: 1 1 200px; }
  button { cursor: pointer; }
  button:hover { background: #20242d; }
  .badge { padding: 4px 10px; border-radius: 999px; font-weight: 600; font-size: 12px; }
  .ok { background: #10331f; color: #57d38c; }
  .bad { background: #3a1414; color: #ff6b6b; }
  .card { background: #141821; border: 1px solid #232936; border-radius: 12px;
          padding: 12px; margin-bottom: 12px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; white-space: nowrap; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #232936; }
  th { color: #8b93a1; font-weight: 500; font-size: 12px; text-transform: uppercase; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
  .g { background: #57d38c; } .r { background: #ff6b6b; } .y { background: #e0b341; }
  .muted { color: #8b93a1; }
  .err { color: #ff6b6b; }
  a { color: #6ab0ff; }
</style>
</head>
<body>
  <h1>local-proxy</h1>
  <div class="sub">Panel de estado del gateway. Se actualiza solo cada 10 s.</div>
  <div class="row">
    <span id="ready" class="badge bad">cargando...</span>
    <span id="updated" class="muted"></span>
  </div>
  <div class="row">
    <input id="token" type="password" placeholder="STATS_TOKEN" autocomplete="off">
    <button id="save">Guardar token</button>
    <button id="refresh">Refrescar</button>
  </div>
  <div id="error" class="err"></div>
  <div class="card">
    <table>
      <thead><tr>
        <th>Exit</th><th>Ubicacion</th><th>Estado</th><th>Circuito</th>
        <th class="num">Activas</th><th class="num">Conexiones</th>
        <th class="num">Subida</th><th class="num">Bajada</th><th class="num">Fallos</th>
      </tr></thead>
      <tbody id="exits"><tr><td colspan="9" class="muted">sin datos</td></tr></tbody>
    </table>
  </div>
  <div class="row muted">
    <span id="sessions">sesiones: -</span>
    <span>·</span>
    <span id="uptime">uptime: -</span>
    <span>·</span>
    <a href="/metrics" target="_blank" rel="noopener">/metrics</a>
  </div>
<script>
(function () {
  var tokenInput = document.getElementById('token');
  var exitsBody = document.getElementById('exits');
  var readyEl = document.getElementById('ready');
  var errorEl = document.getElementById('error');
  var updatedEl = document.getElementById('updated');
  var sessionsEl = document.getElementById('sessions');
  var uptimeEl = document.getElementById('uptime');

  try { tokenInput.value = localStorage.getItem('localproxy_stats_token') || ''; } catch (e) {}

  function fmtBytes(n) {
    if (!n) return '0';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = 0;
    while (n >= 1024 && i < units.length - 1) { n = n / 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + ' ' + units[i];
  }

  function fmtUptime(ms) {
    if (!ms) return '-';
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    if (d) return d + 'd ' + h + 'h';
    if (h) return h + 'h ' + m + 'm';
    if (m) return m + 'm ' + s + 's';
    return s + 's';
  }

  function cell(text, cls) {
    var td = document.createElement('td');
    if (cls) td.className = cls;
    td.textContent = text;
    return td;
  }

  function circuitLabel(c) {
    if (c === 'open') return 'abierto';
    if (c === 'halfOpen') return 'medio-abierto';
    return 'cerrado';
  }

  function render(data) {
    var exits = data.exits || [];
    exitsBody.textContent = '';
    if (!exits.length) {
      var tr = document.createElement('tr');
      var td = cell('sin exits configurados', 'muted');
      td.colSpan = 9;
      tr.appendChild(td);
      exitsBody.appendChild(tr);
    }
    exits.forEach(function (ex) {
      var tr = document.createElement('tr');
      var nameTd = document.createElement('td');
      var dot = document.createElement('span');
      dot.className = 'dot ' + (ex.healthy ? 'g' : 'r');
      nameTd.appendChild(dot);
      nameTd.appendChild(document.createTextNode(ex.name));
      tr.appendChild(nameTd);
      tr.appendChild(cell(ex.location || '-'));
      tr.appendChild(cell(ex.healthy ? 'sano' : 'no sano'));
      var circuitTd = cell(circuitLabel(ex.circuit));
      if (ex.circuit !== 'closed') circuitTd.className = 'err';
      tr.appendChild(circuitTd);
      tr.appendChild(cell(String(ex.active || 0), 'num'));
      tr.appendChild(cell(String(ex.connections || 0), 'num'));
      tr.appendChild(cell(fmtBytes(ex.bytesUp), 'num'));
      tr.appendChild(cell(fmtBytes(ex.bytesDown), 'num'));
      tr.appendChild(cell(String(ex.failures || 0), 'num'));
      exitsBody.appendChild(tr);
    });
    sessionsEl.textContent = 'sesiones: ' + ((data.sessions || []).length);
    if (typeof data.uptimeMs === 'number') uptimeEl.textContent = 'uptime: ' + fmtUptime(data.uptimeMs);
    updatedEl.textContent = 'actualizado ' + new Date().toLocaleTimeString();
  }

  function refreshReady() {
    return fetch('/readyz', { cache: 'no-store' }).then(function (r) {
      return r.json().catch(function () { return { ready: false }; });
    }).then(function (body) {
      var ready = body && body.ready;
      readyEl.textContent = ready ? 'listo' : 'no listo';
      readyEl.className = 'badge ' + (ready ? 'ok' : 'bad');
    }).catch(function () {
      readyEl.textContent = 'sin respuesta';
      readyEl.className = 'badge bad';
    });
  }

  function refreshStats() {
    var token = tokenInput.value.trim();
    if (!token) {
      errorEl.textContent = 'Escribe el STATS_TOKEN para ver las estadisticas.';
      exitsBody.textContent = '';
      return Promise.resolve();
    }
    return fetch('/__stats?token=' + encodeURIComponent(token), { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + (r.status === 403 ? ' (token incorrecto o stats deshabilitadas)' : ''));
        return r.json();
      })
      .then(function (data) { errorEl.textContent = ''; render(data); })
      .catch(function (err) { errorEl.textContent = String(err.message || err); });
  }

  function refresh() { return Promise.all([refreshReady(), refreshStats()]); }

  document.getElementById('save').addEventListener('click', function () {
    try { localStorage.setItem('localproxy_stats_token', tokenInput.value.trim()); } catch (e) {}
    refresh();
  });
  document.getElementById('refresh').addEventListener('click', refresh);
  tokenInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') refresh(); });

  refresh();
  setInterval(refresh, 10000);
})();
</script>
</body>
</html>`;
}
