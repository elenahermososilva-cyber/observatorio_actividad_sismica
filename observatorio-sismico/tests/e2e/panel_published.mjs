// Prueba del panel PUBLICADO (Netlify) a través del túnel real (ngrok), en un Edge headless real.
//
//   node tests/e2e/panel_published.mjs check <url-del-panel> <ruta-de-observatorio-sismico>
//       Carga el panel publicado y comprueba que muestra datos reales de la API a través del túnel.
//
//   node tests/e2e/panel_published.mjs watch <url-del-panel> <ruta-de-observatorio-sismico> [minutos]
//       Vigila el panel mientras una persona CIERRA y vuelve a ABRIR ngrok. Registra cuándo aparece el aviso de fallo,
//       si conserva los eventos de la última lectura y cuándo se recupera solo (sin recargar la página).
//
// Escribe docs/evidencias/panel-publicado-<modo>.json. Requiere Edge en su ruta habitual de Windows.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , MODE, URL_, ROOT, MINUTES = '12'] = process.argv;
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = [];
const note = (message) => { const line = `${new Date().toISOString()} ${message}`; log.push(line); console.log(line); };

const profile = mkdtempSync(join(tmpdir(), 'edge-pub-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1300,1800', 'about:blank'], { stdio: 'ignore' });
let ws, id = 0;
const pending = new Map();

async function connect() {
  for (let i = 0; i < 40; i++) {
    try {
      const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(URL_)}`, { method: 'PUT' })).json();
      ws = new WebSocket(tab.webSocketDebuggerUrl);
      await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
      ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
      return;
    } catch { await sleep(500); }
  }
  throw new Error('no se pudo conectar con Edge');
}
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails)); return r.result.result.value; };
const text = (sel) => ev(`[...document.querySelectorAll(${JSON.stringify(sel)})].map(e=>e.innerText.replace(/\\s+/g,' ').trim()).join(' | ')`);
const waitFor = async (fn, ms = 20000, step = 500) => { const t = Date.now(); while (Date.now() - t < ms) { if (await fn()) return true; await sleep(step); } return false; };
const drawn = async () => { const m = (await text('#h-mapa + .count')).match(/^(\d+) eventos dibujados/); return m ? Number(m[1]) : null; };
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); note(`${ok ? 'OK   ' : 'FALLA'} ${name} ${detail}`); };

async function runCheck() {
  check('el panel publicado carga y dibuja eventos reales', await waitFor(async () => (await drawn()) > 0, 30000), await text('#h-mapa + .count'));
  check('el panel dice que consulta datos en vivo', /EN VIVO/.test(await text('.mode')), await text('.mode'));
  check('no hay aviso de fallo ni de datos desactualizados', (await text('.banner.error, .banner.warn')) === '', await text('.banner'));
  check('estado de la API accesible', /Accesible/.test(await text('.pill')), await text('.pill'));
  check('hay estadísticas', await waitFor(async () => /Calculado en la base de datos/.test(await text('.analysis .count')), 20000), await text('.analysis .count'));
  check('hay gráficos y tabla', (await ev(`document.querySelectorAll('app-bar-chart svg').length`)) >= 4 && (await ev(`document.querySelectorAll('app-event-table tbody tr').length`)) > 0);
  check('la última ingesta de USGS es reciente (< 5 min)', /hace \d+ s|hace [1-4] min/.test(await text('.info dl div:nth-child(3)')), await text('.info dl div:nth-child(3)'));
}

async function runWatch() {
  const deadline = Date.now() + Number(MINUTES) * 60_000;
  check('punto de partida: el panel muestra eventos', await waitFor(async () => (await drawn()) > 0, 30000), await text('#h-mapa + .count'));
  const baseline = await drawn();
  note(`>>> CIERRA ngrok ahora (Ctrl+C). Vigilando hasta ${new Date(deadline).toISOString()}`);
  let failedAt = null, keptEvents = null, countBeforeFailure = baseline, countBeforeRecovery = null, recoveredAt = null, reopenedHint = false;
  while (Date.now() < deadline && recoveredAt === null) {
    const banner = await text('.banner.error');
    // Durante el funcionamiento normal el panel puede incorporar eventos nuevos: se recuerda el último recuento ANTES del fallo.
    if (failedAt === null && banner === '') countBeforeFailure = (await drawn()) ?? countBeforeFailure;
    if (failedAt !== null && banner !== '') countBeforeRecovery = await drawn();
    if (failedAt === null && /No se pudo actualizar/.test(banner)) {
      failedAt = Date.now();
      keptEvents = await drawn();
      note(`FALLO detectado por el panel: «${banner.slice(0, 160)}»`);
      note(`eventos en el mapa: ${keptEvents} (último recuento antes del fallo: ${countBeforeFailure}) · estado: ${await text('.pill')}`);
      note('>>> VUELVE A ABRIR ngrok ahora: ngrok http --url=<dominio-fijo> 8000');
      reopenedHint = true;
    }
    if (failedAt !== null && banner === '') { recoveredAt = Date.now(); note(`RECUPERADO sin recargar la página: estado ${await text('.pill')} · eventos ${await drawn()}`); }
    await sleep(2000);
  }
  check('el panel detectó el túnel cerrado y mostró el aviso', failedAt !== null);
  check('conservó los eventos de la última lectura durante el fallo (antes = durante, y sin cambios hasta el final del fallo)', failedAt !== null && keptEvents === countBeforeFailure && (countBeforeRecovery === null || countBeforeRecovery === keptEvents), `antes ${countBeforeFailure} · al detectar ${keptEvents} · justo antes de recuperar ${countBeforeRecovery}`);
  check('identificó la última lectura correcta', failedAt === null || /hace/.test(await text('.banner.error, .info dl div:nth-child(2)')));
  check('se recuperó solo al reabrir el túnel', recoveredAt !== null, recoveredAt && failedAt ? `tras ${Math.round((recoveredAt - failedAt) / 1000)} s del primer aviso` : (reopenedHint ? 'no se recuperó en el plazo' : ''));
}

try {
  await connect();
  await send('Runtime.enable');
  if (MODE === 'check') await runCheck(); else if (MODE === 'watch') await runWatch(); else throw new Error('modo: check | watch');
} catch (error) {
  check('ejecución sin excepciones', false, String(error));
} finally {
  const failed = results.filter((r) => !r.ok);
  writeFileSync(join(ROOT, 'docs', 'evidencias', `panel-publicado-${MODE}.json`), JSON.stringify({ fecha: new Date().toISOString(), url: URL_, resultados: results, registro: log }, null, 2));
  console.log(`\n${results.length - failed.length}/${results.length} comprobaciones correctas`);
  try { ws?.close(); } catch {}
  edge.kill();
  process.exit(failed.length ? 1 : 0);
}
