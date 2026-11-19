// Regenera las capturas de página completa que cita la memoria, con la interfaz actual y los filtros fijados por URL.
// Edge headless real contra la API real; no para ningún servicio.
//
//   node tests/e2e/capturas_memoria.mjs <url-del-panel> <ruta-de-observatorio-sismico>
//
// Escribe docs/evidencias/panel-live.png, panel-replay.png, analisis/0N-*.png y docs/evidencias/capturas-memoria.json
// (con el total que muestra el mapa y el que muestran los gráficos en cada captura, para comprobar que coinciden).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , BASE, ROOT] = process.argv;
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9336;
const WIDTH = 1280;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), 'edge-cap-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, `--window-size=${WIDTH},900`, 'about:blank'], { stdio: 'ignore' });
let ws, id = 0;
const pending = new Map();
async function connect() {
  for (let i = 0; i < 40; i++) {
    try {
      const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
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
const visibleText = (sel) => ev(`[...document.querySelectorAll(${JSON.stringify(sel)})].filter(e=>e.offsetParent!==null).map(e=>e.innerText.replace(/\\s+/g,' ').trim()).join(' | ')`);
const waitFor = async (fn, ms = 30000, step = 400) => { const t = Date.now(); while (Date.now() - t < ms) { if (await fn()) return true; await sleep(step); } return false; };

const CAPTURES = [
  { file: 'panel-live.png', query: '', tab: 'resumen', note: 'modo en vivo, filtros por defecto (últimas 24 h)' },
  { file: 'panel-replay.png', query: '?mode=replay&range=custom&from=2025-01-01&to=2025-01-03', tab: 'resumen', note: 'reproducción histórica, 1-3 ene 2025' },
  { file: 'analisis/01-live-24h-sin-filtros.png', query: '', tab: 'analisis', note: 'últimas 24 h, sin filtros' },
  { file: 'analisis/02-live-17nov-M4.png', query: '?range=custom&from=2026-11-17&to=2026-11-17&min_mag=4', tab: 'analisis', note: '17-nov-2026, M ≥ 4 (incluye la comparación histórica)' },
  { file: 'analisis/03-live-17nov-M4-sin-pais.png', query: '?range=custom&from=2026-11-17&to=2026-11-17&min_mag=4&country=none', tab: 'resumen', note: '17-nov-2026, M ≥ 4, sin país asignado' },
  { file: 'analisis/04-live-17y18nov-pais-USA.png', query: '?range=custom&from=2026-11-17&to=2026-11-18&country=USA', tab: 'resumen', note: '17 y 18-nov-2026, país USA' },
];

mkdirSync(join(ROOT, 'docs', 'evidencias', 'analisis'), { recursive: true });
const report = [];
try {
  await connect();
  await send('Page.enable');
  for (const c of CAPTURES) {
    await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: 900, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: 'about:blank' });
    await sleep(300);
    await send('Page.navigate', { url: `${BASE}${c.query}#${c.tab}` });
    const read = (sel) => ev(`(document.querySelector(${JSON.stringify(sel)})?.textContent ?? '').replace(/\\s+/g,' ').trim()`);
    const statsOk = await waitFor(async () => /Calculado en la base de datos/.test(await read('.analysis .count')), 30000);
    const statsText = statsOk ? await read('.analysis .count') : '';
    const totalOf = (t) => Number((t.match(/de (\d+) que cumplen/) ?? t.match(/^(\d+) eventos/) ?? [])[1] ?? NaN);
    const wanted = Number((statsText.match(/sobre (\d+)/) ?? [])[1] ?? NaN);
    // el mapa y los gráficos llegan por consultas distintas: se espera a que ambos describan el mismo conjunto
    const counted = await waitFor(async () => { const t = await read('#h-mapa + .count'); return /eventos dibujados/.test(t) && (wanted === 0 || totalOf(t) === wanted || (/^\d+ eventos/.test(t) && Number(t.match(/^(\d+)/)[1]) === wanted)); }, 20000);
    const mapText = await read('#h-mapa + .count');
    if (c.tab === 'resumen') await ev(`document.querySelector('.leaflet-tile-loaded') !== null`);
    await sleep(3500); // teselas del mapa base
    // Página completa sin cambiar el tamaño de la ventana (el mapa mide 56vh: redimensionar lo deformaría)
    const height = await ev(`Math.ceil(document.documentElement.scrollHeight)`);
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: WIDTH, height, scale: 1 } });
    writeFileSync(join(ROOT, 'docs', 'evidencias', c.file), Buffer.from(shot.result.data, 'base64'));
    const mapTotal = totalOf(mapText);
    const statsTotal = wanted;
    const banners = await visibleText('.banner');
    report.push({ file: c.file, note: c.note, url: `${BASE}${c.query}#${c.tab}`, mapa_total: mapTotal, graficos_total: statsTotal,
      coinciden: statsText === '' ? null : mapTotal === statsTotal, avisos: banners, filtros: await visibleText('.filters select, .filters input') });
    console.log(`${counted ? 'OK   ' : 'FALLA'} ${c.file}  mapa=${mapTotal} gráficos=${Number.isNaN(statsTotal) ? 'n/a' : statsTotal}  ${banners ? 'avisos: ' + banners.slice(0, 80) : ''}`);
  }
} finally {
  writeFileSync(join(ROOT, 'docs', 'evidencias', 'capturas-memoria.json'), JSON.stringify({ at: new Date().toISOString(), capturas: report }, null, 2));
  try { ws?.close(); } catch { /* */ }
  edge.kill();
}
