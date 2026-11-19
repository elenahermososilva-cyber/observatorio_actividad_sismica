// Prueba del panel por secciones en un Edge headless real: pestañas, ficha de un evento (desde la tabla, la dispersión y el
// resumen), gráficos interactivos y pestaña «Histórico 2025» con paginación en el servidor. No para ningún servicio.
//
//   node tests/e2e/panel_secciones.mjs <url-del-panel> <ruta-de-observatorio-sismico>
//
// Escribe docs/evidencias/panel-secciones.json y capturas en docs/evidencias/secciones/*.png.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , URL_, ROOT] = process.argv;
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9335;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), 'edge-sec-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1366,900', 'about:blank'], { stdio: 'ignore' });
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
const visibleText = (sel) => ev(`[...document.querySelectorAll(${JSON.stringify(sel)})].filter(e=>e.offsetParent!==null).map(e=>e.innerText.replace(/\\s+/g,' ').trim()).join(' | ')`);
const waitFor = async (fn, ms = 20000, step = 400) => { const t = Date.now(); while (Date.now() - t < ms) { if (await fn()) return true; await sleep(step); } return false; };
const clickTab = (label) => ev(`[...document.querySelectorAll('.tabs button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`);
const shotsDir = join(ROOT, 'docs', 'evidencias', 'secciones');
mkdirSync(shotsDir, { recursive: true });
const shot = async (name) => {
  await sleep(700);
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  writeFileSync(join(shotsDir, `${name}.png`), Buffer.from(r.result.data, 'base64'));
};
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'OK   ' : 'FALLA'} ${name} ${detail}`); };

try {
  await connect();
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
  check('el resumen carga eventos', await waitFor(async () => /^[1-9]\d* eventos dibujados/.test(await visibleText('#h-mapa + .count')), 30000), await visibleText('#h-mapa + .count'));
  await waitFor(async () => /conectado/i.test(await visibleText('.conn')), 10000);
  check('hay 5 pestañas', (await ev(`document.querySelectorAll('.tabs button').length`)) === 5);
  check('el resumen muestra indicadores', (await ev(`[...document.querySelectorAll('.stat')].filter(e=>e.offsetParent!==null).length`)) >= 4, await visibleText('.stat-label'));
  check('indicador de conexión visible', /conectado/i.test(await visibleText('.conn')), await visibleText('.conn'));
  await shot('01-resumen');

  await clickTab('Análisis');
  check('pestaña Análisis: solo se ve el análisis', await waitFor(async () => (await visibleText('#h-analisis')) === 'Análisis' && (await visibleText('#h-mapa')) === ''), await visibleText('h2'));
  check('Análisis: gráficos dibujados', await waitFor(async () => (await ev(`document.querySelectorAll('.analysis app-bar-chart svg').length`)) >= 4 && (await ev(`document.querySelectorAll('app-scatter-chart circle').length`)) > 0));
  // Tooltip: pasar el ratón sobre una barra del gráfico horario
  await ev(`(()=>{const r=document.querySelector('.analysis app-bar-chart rect.bar'); r.dispatchEvent(new MouseEvent('mouseenter',{bubbles:false})); return true})()`);
  check('Análisis: la barra señalada muestra su valor', await waitFor(async () => /terremotos/.test(await visibleText('app-bar-chart .tooltip')), 4000), await visibleText('app-bar-chart .tooltip'));
  check('la URL refleja la pestaña', (await ev('location.hash')) === '#analisis');
  await shot('02-analisis');
  await ev(`document.querySelector('app-scatter-chart').scrollIntoView({block:'center'})`);
  await ev(`(()=>{const c=document.querySelector('app-scatter-chart circle'); c.dispatchEvent(new MouseEvent('mouseenter',{bubbles:false})); return true})()`);
  check('Dispersión: el punto señalado muestra el evento', await waitFor(async () => /Pulsa para ver la ficha/.test(await visibleText('app-scatter-chart .tooltip')), 4000), await visibleText('app-scatter-chart .tooltip'));
  await shot('03-dispersion');
  await ev(`document.querySelector('app-scatter-chart circle').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  check('Dispersión: al pulsar un punto se abre su ficha', await waitFor(async () => /identificador/i.test(await visibleText('app-event-detail'))), (await visibleText('app-event-detail h2')));
  await ev(`document.querySelector('app-event-detail .back').click()`);
  check('«Volver» regresa a la pestaña de origen', await waitFor(async () => (await visibleText('#h-analisis')) === 'Análisis'));

  await clickTab('Eventos');
  check('pestaña Eventos: tabla con filas', await waitFor(async () => (await ev(`[...document.querySelectorAll('app-event-table tbody tr.clickable')].filter(e=>e.offsetParent!==null).length`)) > 0));
  const place = await ev(`[...document.querySelectorAll('app-event-table tbody tr.clickable')].find(e=>e.offsetParent!==null).querySelector('button.link').textContent.trim()`);
  await ev(`[...document.querySelectorAll('app-event-table tbody tr.clickable')].find(e=>e.offsetParent!==null).click()`);
  check('Eventos: al pulsar una fila se abre su ficha', await waitFor(async () => (await visibleText('app-event-detail h2')) === place), place);
  check('Ficha: muestra mapa del epicentro y enlace a USGS', await waitFor(async () => (await ev(`document.querySelectorAll('app-event-detail .leaflet-marker-pane, app-event-detail path.leaflet-interactive').length`)) > 0) && /earthquake\.usgs\.gov\/earthquakes\/eventpage\//.test(await ev(`document.querySelector('app-event-detail a').href`)));
  await shot('04-ficha-evento');
  await ev(`document.querySelector('app-event-detail .back').click()`);

  await clickTab('Histórico 2025');
  check('Histórico: total de 2025 desde la API', await waitFor(async () => /18[.,]?302/.test(await visibleText('.hist-main .stat-value')), 30000), await visibleText('.hist-main .stat-value'));
  const firstPage = await ev(`[...document.querySelectorAll('.hist-main app-event-table tbody tr td:last-child')].map(e=>e.textContent.trim()).join(',')`);
  check('Histórico: 25 filas por página', (await ev(`document.querySelectorAll('.hist-main app-event-table tbody tr.clickable').length`)) === 25);
  await shot('05-historico');
  await ev(`[...document.querySelectorAll('.hist-main .pager button')].pop().click()`);
  check('Histórico: «Siguiente» trae otra página del servidor', await waitFor(async () => /Página 2 de/.test(await visibleText('.hist-main .pager span')) && (await ev(`[...document.querySelectorAll('.hist-main app-event-table tbody tr td:last-child')].map(e=>e.textContent.trim()).join(',')`)) !== firstPage), await visibleText('.hist-main .pager span'));
  // Filtro: Japón, M ≥ 5
  await ev(`(()=>{const f=document.querySelector('.hist-filters'); const t=f.querySelector('input[type=text]'); t.value='5'; t.dispatchEvent(new Event('input',{bubbles:true})); const s=f.querySelectorAll('select')[0]; s.value='JPN'; s.dispatchEvent(new Event('change',{bubbles:true})); f.querySelector('button.primary').click(); return true})()`);
  check('Histórico: filtro país + magnitud aplicado en el servidor', await waitFor(async () => /Japón/.test(await visibleText('.hist-main app-event-table')) && !/Estados Unidos/.test(await visibleText('.hist-main app-event-table')), 20000), await visibleText('.hist-main .stat-value'));
  await shot('06-historico-japon-m5');
  await ev(`document.querySelector('.hist-main app-event-table tbody tr.clickable').click()`);
  check('Histórico: ficha de un evento de 2025', await waitFor(async () => /histórico 2025/i.test(await visibleText('app-event-detail .eyebrow')) && /2025-/.test(await visibleText('app-event-detail'))), await visibleText('app-event-detail h2'));
  await shot('07-ficha-historico');
  await ev(`document.querySelector('app-event-detail .back').click()`);

  await clickTab('Estado del sistema');
  check('Estado del sistema: API accesible', await waitFor(async () => /Accesible/.test(await visibleText('.info .pill'))), await visibleText('.info .pill'));
  await shot('08-estado');

  await clickTab('Resumen');
  await ev(`document.querySelector('.stat-link').click()`);
  check('Resumen: el último terremoto abre su ficha', await waitFor(async () => /identificador/i.test(await visibleText('app-event-detail'))));
} catch (error) {
  check('ejecución sin excepciones', false, String(error));
} finally {
  const ok = results.filter((r) => r.ok).length;
  console.log(`\n${ok}/${results.length} comprobaciones correctas`);
  writeFileSync(join(ROOT, 'docs', 'evidencias', 'panel-secciones.json'),
    JSON.stringify({ url: URL_, at: new Date().toISOString(), ok, total: results.length, results }, null, 2));
  try { ws?.close(); } catch { /* */ }
  edge.kill();
  process.exit(ok === results.length ? 0 : 1);
}
