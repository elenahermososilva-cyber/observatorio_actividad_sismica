// Prueba de extremo a extremo del panel en un Edge real (headless) mediante el protocolo DevTools.
// Requisitos: pila Docker levantada, `npm start` en frontend/ (http://localhost:4200) y config.json con "refreshMs": 30000
// (el panel no refresca más rápido de 30 s). Esta prueba PARA y ARRANCA el servicio `api` (docker compose stop/start api).
//   node tests/e2e/panel_e2e.mjs http://localhost:4200/ "<ruta absoluta de observatorio-sismico>"
// Escribe docs/evidencias/panel-e2e.json.
import { spawn, execSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const URL_ = process.argv[2] ?? 'http://localhost:4200/';
const PORT = 9333;
const ROOT = process.argv[3];
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'OK  ' : 'FALLA'} ${name} ${detail}`); };

const profile = mkdtempSync(join(tmpdir(), 'edge-e2e-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1300,1800', 'about:blank'], { stdio: 'ignore' });
let ws, id = 0; const pending = new Map();
async function connect() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(URL_)}`, { method: 'PUT' });
      const tab = await r.json();
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
const setField = (sel, value, evt = 'input') => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(evt)},{bubbles:true}));return true})()`);
const click = (sel) => ev(`document.querySelector(${JSON.stringify(sel)}).click()`);
const waitFor = async (fn, ms = 15000, step = 500) => { const t = Date.now(); while (Date.now() - t < ms) { if (await fn()) return true; await sleep(step); } return false; };
const dockerApi = (cmd) => execSync(`docker compose ${cmd} api`, { cwd: ROOT, stdio: 'ignore' });
const num = (s, re) => { const m = s.match(re); return m ? Number(m[1].replace(/\./g, '')) : null; };

try {
  await connect();
  await send('Runtime.enable');
  // ---------------------------------------------------------------- carga inicial
  check('carga inicial: eventos dibujados', await waitFor(async () => /eventos dibujados/.test(await text('#h-mapa + .count')) && num(await text('#h-mapa + .count'), /^(\d+) eventos/) > 0), await text('#h-mapa + .count'));
  check('hay estadísticas', await waitFor(async () => /Calculado en la base de datos/.test(await text('.analysis .count'))));
  check('hay 3 gráficos de barras + tabla', (await ev(`document.querySelectorAll('app-bar-chart svg').length`)) >= 4, String(await ev(`document.querySelectorAll('app-bar-chart svg').length`)));
  check('tabla con filas', (await ev(`document.querySelectorAll('app-event-table tbody tr').length`)) > 0);
  check('leyenda visible con ND', /ND/.test(await text('app-event-map .legend')));

  // ---------------------------------------------------------------- coherencia mapa/gráficos con filtros
  async function totals() {
    const map = await text('#h-mapa + .count'); const stats = await text('.analysis .count');
    return { mapTotal: num(map, /de (\d+) que cumplen/) ?? num(map, /^(\d+) eventos/), statsTotal: num(stats, /sobre (\d+) eventos/), map, stats };
  }
  await setField('input[inputmode=decimal]', '4');
  await click('button.primary');
  await sleep(3500);
  let t = await totals();
  check('min_mag=4: total del mapa = total de estadísticas', t.mapTotal === t.statsTotal && t.mapTotal !== null, JSON.stringify([t.mapTotal, t.statsTotal]));
  const steps = await ev(`(()=>{const c=[...document.querySelectorAll('app-bar-chart')][3]; const v=[...c.querySelectorAll('tbody th')].map(e=>Number(e.textContent.trim().replace('.','').replace(',','.'))); return [...new Set(v.slice(1).map((x,i)=>x-v[i]))]; })()`);
  check('histograma de profundidad continuo: todos los intervalos separados 10 km', steps.length === 1 && steps[0] === 10, JSON.stringify(steps));
  await ev(`(()=>{const sel=[...document.querySelectorAll('.filters select')].pop(); sel.value='none'; sel.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await click('button.primary'); await sleep(3500);
  t = await totals();
  check('país «Sin país asignado»: coherente mapa/estadísticas', t.mapTotal === t.statsTotal, JSON.stringify([t.mapTotal, t.statsTotal]));
  const groups = await ev(`[...document.querySelectorAll('app-bar-chart')][1].innerText`);
  check('el ranking solo contiene «Sin país asignado»', /Sin país asignado/.test(groups) && !/Estados Unidos/.test(groups));

  // validación sin llamar a la API
  await setField('input[inputmode=decimal]', 'abc');
  await click('button.primary'); await sleep(500);
  check('min_mag inválido muestra error', /magnitud mínima/i.test(await text('.field-error')), await text('.field-error'));

  // fechas concretas
  await setField('input[inputmode=decimal]', '');
  await ev(`(()=>{const s=document.querySelector('.filters select'); s.value='custom'; s.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await sleep(300);
  await ev(`(()=>{const sel=[...document.querySelectorAll('.filters select')].pop(); sel.value=''; sel.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await setField('input[type=date]:nth-of-type(1)', '2026-11-17');
  await ev(`(()=>{const d=document.querySelectorAll('input[type=date]'); d[0].value='2026-11-17'; d[0].dispatchEvent(new Event('input',{bubbles:true})); d[1].value='2026-11-17'; d[1].dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await click('button.primary'); await sleep(3500);
  t = await totals();
  check('rango 17-nov completo: coherente y con eventos', t.mapTotal === t.statsTotal && t.mapTotal > 0, JSON.stringify([t.mapTotal, t.statsTotal]) + ' ' + (await text('.info dl div:nth-child(4)')));
  await ev(`document.querySelector('.filters button:not(.primary)').click()`); await sleep(3000);

  // ---------------------------------------------------------------- filas 9 y 10: API caída y recuperada
  const before = await text('#h-mapa + .count');
  const beforeOk = await text('.info dl div:nth-child(2)');
  console.log('API caída…'); dockerApi('stop');
  const failed = await waitFor(async () => /No se pudo actualizar/.test(await text('.banner.error')), 50000, 1000);
  check('FILA 9: con la API parada el panel muestra el fallo', failed, await text('.banner.error'));
  const during = await text('#h-mapa + .count');
  check('FILA 9: conserva los eventos de la última lectura', during === before && /hace/.test(await text('.banner.error')), during);
  check('FILA 9: identifica la última lectura correcta', (await text('.info dl div:nth-child(2)')) === beforeOk || /hace/.test(await text('.info dl div:nth-child(2)')), await text('.info dl div:nth-child(2)'));
  check('FILA 9: estado de la API «Sin respuesta»', /Sin respuesta/.test(await text('.pill')), await text('.pill'));
  console.log('API recuperada…'); dockerApi('start');
  const recovered = await waitFor(async () => (await text('.banner.error')) === '', 80000, 1500);
  check('FILA 10: al volver la API se recupera sola, sin recargar la página', recovered, await text('.banner'));
  check('FILA 10: vuelve «Accesible/Datos desactualizados» según salud', /Accesible|Datos desactualizados/.test(await text('.pill')), await text('.pill'));
} catch (error) {
  check('ejecución sin excepciones', false, String(error));
} finally {
  const failed = results.filter((r) => !r.ok);
  writeFileSync(join(ROOT, 'docs', 'evidencias', 'panel-e2e.json'), JSON.stringify({ fecha: new Date().toISOString(), url: URL_, resultados: results }, null, 2));
  console.log(`\n${results.length - failed.length}/${results.length} comprobaciones correctas`);
  try { ws?.close(); } catch {}
  edge.kill();
  process.exit(failed.length ? 1 : 0);
}
