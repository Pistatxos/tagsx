// Lo que comparten Etiquetas, Historial y Ajustes: llamadas al servidor, avisos, modal y la navegación.
'use strict';
const $ = id => document.getElementById(id);
// Safari y los gestores de contraseñas proponen correos o contactos en cualquier campo: aquí no hay nada que rellenar
const NOFILL = 'autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" data-1p-ignore data-lpignore="true" data-form-type="other"';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const n = x => Number(x).toLocaleString('es-ES');

async function api(url, opciones = {}) {
  const cabeceras = opciones.body instanceof FormData ? {} : { 'Content-Type': 'application/json' };
  const r = await fetch(url, { credentials: 'same-origin', headers: cabeceras, ...opciones });
  let datos;
  try { datos = await r.json(); } catch { datos = { error: r.status === 403 ? 'Sesión no válida: abre la URL que sale en la terminal.' : `Error ${r.status}` }; }
  if (!r.ok) { const e = new Error(datos.error || `Error ${r.status}`); e.datos = datos; throw e; }
  return datos;
}
const post = (url, datos) => api(url, { method: 'POST', body: JSON.stringify(datos) });

function toast(mensaje, mal) {
  const t = document.createElement('div');
  t.className = 'toast' + (mal ? ' mal' : '');
  t.textContent = mensaje;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), mal ? 7000 : 3500);
}

function fecha(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString('es-ES', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

// ------------------------------------------------ estado compartido (config leída del servidor)
const TX = { estado: null, oyentes: [], pendientes: () => 0 };
async function refrescarEstado() {
  TX.estado = await api('/api/estado');
  TX.oyentes.forEach(f => f(TX.estado));
  return TX.estado;
}
function cfg() {
  const c = TX.estado && TX.estado.config;
  return c || { perfil_aws: '', regiones: [], servicios: [], esquema: [], catalogos: {}, minusculas: true };
}

// Lo mismo que core/reglas.py, para pintar avisos sin esperar al servidor
const MAX_VALOR = 256, MAX_CLAVE = 128;
const reservada = k => k.toLowerCase().startsWith('aws:') || k.startsWith('kubernetes.io/');
function avisosValor(k, v) {
  const c = cfg(), avisos = [];
  if (!v) return avisos;
  if (c.minusculas && c.esquema.includes(k) && k !== 'Name' && v !== v.toLowerCase()) avisos.push(`${k}: lleva mayúsculas`);
  const cat = (c.catalogos || {})[k];
  if (cat && cat.length && !cat.includes(v) && v.toLowerCase() !== 'none') avisos.push(`${k}: '${v}' no está en el catálogo (${cat.join(', ')})`);
  return avisos;
}
function erroresValor(k, v) {
  const e = [];
  if (v && v.length > MAX_VALOR) e.push(`${k}: el valor pasa de ${MAX_VALOR} caracteres`);
  return e;
}

// ------------------------------------------------ modal
const modal = {
  abierto: () => !$('modal').hidden,
  abrir(html) { $('modalCuerpo').innerHTML = html; $('modal').hidden = false; },
  cerrar() { $('modal').hidden = true; $('modalCuerpo').innerHTML = ''; $('modalCuerpo').onclick = null; },
};
$('modalCerrar').onclick = modal.cerrar;
$('modal').addEventListener('mousedown', e => { if (e.target === $('modal')) modal.cerrar(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.abierto()) modal.cerrar(); });

// ------------------------------------------------ navegación: #/, #/historial y #/ajustes
const VISTAS = { '#/historial': 'historial', '#/ajustes': 'ajustes' };
const TITULOS = { etiquetas: 'TagsX', historial: 'Historial · TagsX', ajustes: 'Ajustes · TagsX' };
function mostrarVista() {
  const vista = VISTAS[location.hash] || 'etiquetas';
  $('vEtiquetas').hidden = vista !== 'etiquetas';
  $('vHistorial').hidden = vista !== 'historial';
  $('vAjustes').hidden = vista !== 'ajustes';
  document.querySelectorAll('.lateral a[data-vista]').forEach(a => a.classList.toggle('activo', a.dataset.vista === vista));
  document.title = TITULOS[vista];
  window.dispatchEvent(new CustomEvent('vista', { detail: vista }));
}
window.addEventListener('hashchange', mostrarVista);

// Perfil y cuenta, abajo en la barra lateral
TX.oyentes.push(async estado => {
  const c = estado.config;
  if (!c) { $('tDonde').innerHTML = '<span class="error">Config ilegible</span>'; return; }
  const regiones = (c.regiones || []).join(', ') || '—';
  $('tDonde').innerHTML = `<b>${esc(c.perfil_aws || 'perfil por defecto')}</b><span>${esc(regiones)}</span><span id="tCuenta">…</span>`;
  try {
    const cuenta = await api('/api/cuenta');
    if ($('tCuenta')) $('tCuenta').textContent = cuenta.account;
  } catch (e) {
    if ($('tCuenta')) { $('tCuenta').textContent = 'sin credenciales'; $('tCuenta').className = 'error'; $('tCuenta').title = e.message; }
  }
});

window.addEventListener('beforeunload', e => { if (TX.pendientes() > 0) { e.preventDefault(); e.returnValue = ''; } });
