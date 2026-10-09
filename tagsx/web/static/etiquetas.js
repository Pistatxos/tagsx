// Etiquetas: la instantánea de la cuenta en una tabla tipo hoja de cálculo, con cobertura,
// filtros, edición en bloque y «Revisar» (relee AWS) → «Aplicar».
'use strict';
const E = {
  datos: null, recursos: [], porArn: new Map(),
  ed: {},          // arn -> {clave: valor | null (= borrar)}
  extras: [],      // columnas añadidas con «+ columna» o al editar en bloque
  sel: new Set(),
  f: { texto: '', servicio: '', entorno: '', falta: '', avisos: false, cambios: false, otras: false },
  orden: { col: 'nombre', dir: 1 },
  pagina: 0, porPagina: 50,
  visibles: [],    // lo filtrado y ordenado la última vez que se pintó la tabla
  cols: [],        // columnas editables pintadas
};
const SIN_VALOR = '(sin valor)';

// ------------------------------------------------------------------ valores y cambios
function valor(r, k) {
  const ed = E.ed[r.arn];
  if (ed && k in ed) return ed[k] ?? '';
  return r.tags[k] ?? '';
}
// Vaciar una celda que tenía valor = borrar esa etiqueta; dejarla como estaba = sin cambio
function setEdicion(r, k, v) {
  const orig = r.tags[k];
  const ed = E.ed[r.arn] || (E.ed[r.arn] = {});
  if (v === '') { if (orig === undefined) delete ed[k]; else ed[k] = null; }
  else if (v === orig) delete ed[k];
  else ed[k] = v;
  if (!Object.keys(ed).length) delete E.ed[r.arn];
}
function limpiarEdiciones(arn) {
  const r = E.porArn.get(arn), ed = E.ed[arn];
  if (!ed) return;
  if (!r) { delete E.ed[arn]; return; }
  for (const k of Object.keys(ed)) {
    if ((ed[k] === null && !(k in r.tags)) || ed[k] === r.tags[k]) delete ed[k];
  }
  if (!Object.keys(ed).length) delete E.ed[arn];
}
function contarCambios() {
  let total = 0;
  for (const ed of Object.values(E.ed)) total += Object.keys(ed).length;
  return { total, recursos: Object.keys(E.ed).length };
}
TX.pendientes = () => contarCambios().total;

// Borrador: los cambios sin aplicar sobreviven a cerrar la pestaña (solo en este navegador)
const CLAVE_BORRADOR = 'tagsx-borrador';
function guardarBorrador() {
  try {
    if (!E.datos) return;
    localStorage.setItem(CLAVE_BORRADOR, JSON.stringify({ cuenta: E.datos.cuenta, ed: E.ed, extras: E.extras }));
  } catch { /* sin almacenamiento: no pasa nada */ }
}
function recuperarBorrador() {
  try {
    const b = JSON.parse(localStorage.getItem(CLAVE_BORRADOR) || 'null');
    if (!b || b.cuenta !== E.datos.cuenta) return;
    E.ed = b.ed || {};
    E.extras = b.extras || [];
    Object.keys(E.ed).forEach(limpiarEdiciones);
  } catch { /* borrador ilegible: se ignora */ }
}

// ------------------------------------------------------------------ columnas y avisos
function claveEntorno() { return cfg().esquema.find(k => /^env/i.test(k)) || ''; }
function columnas() {
  const esquema = cfg().esquema;
  const extras = E.extras.filter(k => !esquema.includes(k));
  const otras = E.f.otras ? E.datos.claves.filter(k => !esquema.includes(k) && !extras.includes(k)) : [];
  return { esquema, extras, otras, todas: [...esquema, ...extras, ...otras] };
}
function asegurarColumna(k) {
  if (!columnas().todas.includes(k) && !E.extras.includes(k)) E.extras.push(k);
}
function avisosRecurso(r) {
  const out = [];
  for (const k of cfg().esquema) out.push(...avisosValor(k, valor(r, k)));
  return out;
}
function estadoCelda(r, k) {
  const ed = E.ed[r.arn], orig = r.tags[k];
  const titulo = [];
  let cls = '';
  if (ed && k in ed) {
    if (ed[k] === null) { cls = 'borra'; titulo.push(`Se borra (ahora: ${orig})`); }
    else { cls = 'cambia'; titulo.push(orig === undefined ? 'Etiqueta nueva' : `Antes: ${orig}`); }
  }
  const v = valor(r, k), err = erroresValor(k, v), av = avisosValor(k, v);
  if (err.length) cls += ' mal'; else if (av.length) cls += ' aviso';
  return { cls, titulo: [...titulo, ...err, ...av].join('\n') };
}

// ------------------------------------------------------------------ filtrar y ordenar
function pasa(r, ignorarFalta) {
  const f = E.f;
  if (f.texto) {
    const t = f.texto.toLowerCase();
    const ed = E.ed[r.arn] || {};
    const texto = [r.nombre, r.arn, ...Object.values(r.tags), ...Object.values(ed).filter(Boolean)].join('\n').toLowerCase();
    if (!texto.includes(t)) return false;
  }
  if (f.servicio && r.servicio !== f.servicio) return false;
  if (f.entorno) {
    const v = valor(r, claveEntorno());
    if (f.entorno === SIN_VALOR ? v !== '' : v !== f.entorno) return false;
  }
  if (!ignorarFalta && f.falta && valor(r, f.falta) !== '') return false;
  if (f.avisos && !avisosRecurso(r).length) return false;
  if (f.cambios && !E.ed[r.arn]) return false;
  return true;
}
function ordenar(lista) {
  const { col, dir } = E.orden;
  const clave = col === 'nombre' ? r => r.nombre.toLowerCase()
    : col === 'servicio' ? r => `${r.servicio}/${r.tipo}`
    : r => valor(r, col).toLowerCase();
  return lista.map(r => [clave(r), r])
    .sort((a, b) => (a[0] === '') - (b[0] === '') || dir * a[0].localeCompare(b[0], 'es', { numeric: true }))
    .map(x => x[1]);
}

// ------------------------------------------------------------------ pintar
function pintarTodo() {
  if (!E.datos) return;
  pintarFuente();
  pintarSelects();
  pintarCobertura();
  pintarTabla();
}
function pintarFuente() {
  const d = E.datos;
  const regiones = (d.regiones || []).join(', ');
  $('eFuente').textContent = `Leído ${fecha(d.fecha)} · ${n(d.recursos.length)} recursos · cuenta ${d.cuenta} · ${regiones} + global`;
  $('eFuente').title = `Perfil: ${d.perfil || 'por defecto'}`;
}
function opciones(valores, elegido, todos) {
  return `<option value="">${esc(todos)}</option>` + valores.map(([v, c]) =>
    `<option value="${esc(v)}"${v === elegido ? ' selected' : ''}>${esc(v)}${c != null ? ` (${c})` : ''}</option>`).join('');
}
function contar(fn) {
  const m = new Map();
  for (const r of E.recursos) { const v = fn(r); m.set(v, (m.get(v) || 0) + 1); }
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], 'es'));
}
function pintarSelects() {
  $('fServicio').innerHTML = opciones(contar(r => r.servicio), E.f.servicio, 'Todos');
  const ke = claveEntorno();
  $('fEntornoCaja').hidden = !ke;
  if (ke) {
    const valores = contar(r => valor(r, ke) || SIN_VALOR);
    $('fEntorno').innerHTML = opciones(valores, E.f.entorno, 'Todos');
  }
  // Los controles con un filtro puesto, resaltados
  $('fTexto').classList.toggle('activo', !!E.f.texto);
  $('fServicio').classList.toggle('activo', !!E.f.servicio);
  $('fEntorno').classList.toggle('activo', !!E.f.entorno);
  for (const [id, k] of [['fAvisos', 'avisos'], ['fCambios', 'cambios'], ['fOtras', 'otras']]) {
    $(id).checked = E.f[k];
    $(id).closest('.check').classList.toggle('activo', E.f[k]);
  }
}
// Una tarjeta por etiqueta del esquema. Con «Falta X» puesto, la cobertura se calcula sin ese filtro.
function pintarCobertura() {
  const base = E.recursos.filter(r => pasa(r, true));
  $('eCobertura').innerHTML = cfg().esquema.map(k => {
    const con = base.filter(r => valor(r, k) !== '').length;
    const falta = base.length - con;
    const pct = base.length ? Math.floor(100 * con / base.length) : 100;
    const activa = E.f.falta === k;
    const nivel = pct === 100 && !falta ? 'completa' : pct < 50 ? 'muy-bajo' : pct < 80 ? 'bajo' : '';
    const pie = falta ? `−${n(falta)}` : '';
    const titulo = activa ? `Mostrando los ${n(falta)} sin ${k}. Pulsa para quitar el filtro`
      : falta ? `${n(falta)} recursos sin ${k}. Pulsa para verlos` : `Todos tienen ${k}`;
    return `<button type="button" class="cob ${nivel}${activa ? ' activa' : ''}" data-k="${esc(k)}" ${!falta && !activa ? 'disabled' : ''}
      title="${esc(titulo)}">
      <span class="cob-k">${esc(k)}</span><span class="cob-pct">${pct}%</span>
      <span class="cob-falta">${pie}</span><span class="cob-barra"><i data-pct="${pct}"></i></span></button>`;
  }).join('');
  // CSP sin estilos en línea: el ancho se pone desde aquí
  $('eCobertura').querySelectorAll('.cob-barra i').forEach(i => { i.style.width = `${i.dataset.pct}%`; });
}
function pintarActivos() {
  const f = E.f, chips = [];
  const chip = (texto, quitar) => chips.push(`<button type="button" class="filtro-chip" data-quitar="${quitar}" title="Quitar">${esc(texto)}<span>×</span></button>`);
  if (f.texto) chip(`«${f.texto}»`, 'texto');
  if (f.falta) chip(`Falta ${f.falta}`, 'falta');
  if (f.servicio) chip(`Servicio: ${f.servicio}`, 'servicio');
  if (f.entorno) chip(`${claveEntorno()}: ${f.entorno}`, 'entorno');
  if (f.avisos) chip('Con avisos', 'avisos');
  if (f.cambios) chip('Con cambios', 'cambios');
  $('eActivos').innerHTML = `<span>Mostrando <b>${n(E.visibles.length)}</b> de ${n(E.recursos.length)}</span>`
    + (chips.length ? ` · ${chips.join('')} · <button type="button" class="enlace" data-quitar="todos">Quitar todos</button>` : '');
}
function datalists(cols) {
  const cat = cfg().catalogos || {};
  $('eListas').innerHTML = cols.map((k, j) => {
    const frec = new Map();
    for (const r of E.recursos) { const v = r.tags[k]; if (v) frec.set(v, (frec.get(v) || 0) + 1); }
    const valores = [...new Set([...(cat[k] || []), ...[...frec.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40).map(x => x[0])])];
    return `<datalist id="dl${j}">${valores.map(v => `<option value="${esc(v)}">`).join('')}</datalist>`;
  }).join('');
  const claves = [...new Set([...cfg().esquema, ...E.extras, ...E.datos.claves])];
  $('dlClaves').innerHTML = claves.map(k => `<option value="${esc(k)}">`).join('');
}
function pintarTabla() {
  E.visibles = ordenar(E.recursos.filter(r => pasa(r, false)));
  const paginas = Math.max(1, Math.ceil(E.visibles.length / E.porPagina));
  E.pagina = Math.min(E.pagina, paginas - 1);
  const c = columnas();
  E.cols = c.todas;
  datalists(c.todas);

  const flecha = col => E.orden.col === col ? `<span class="flecha">${E.orden.dir > 0 ? '▲' : '▼'}</span>` : '';
  const th = (col, texto, cls = '') => `<th class="${cls}"><button type="button" class="orden" data-col="${esc(col)}">${esc(texto)}${flecha(col)}</button></th>`;
  $('eCabeza').innerHTML = `<tr><th class="c-sel"><input type="checkbox" id="selTodo" title="Seleccionar todo lo filtrado (${E.visibles.length})"></th>`
    + th('nombre', 'Recurso', 'c-rec') + th('servicio', 'Servicio')
    + c.esquema.map(k => th(k, k, 'esquema')).join('')
    + c.extras.map(k => th(k, k, 'extra')).join('')
    + c.otras.map(k => th(k, k)).join('')
    + (E.f.otras ? '' : '<th><span class="orden">Otras</span></th>') + '</tr>';

  const pagina = E.visibles.slice(E.pagina * E.porPagina, (E.pagina + 1) * E.porPagina);
  if (!pagina.length) {
    $('eCuerpo').innerHTML = `<tr><td class="vacio" colspan="${c.todas.length + 4}">Nada con estos filtros.</td></tr>`;
  } else {
    $('eCuerpo').innerHTML = pagina.map(r => fila(r, c)).join('');
  }
  pintarPaginas(paginas);
  pintarActivos();
  pintarBarra();
}
function fila(r, c) {
  const celdas = c.todas.map((k, j) => {
    const { cls, titulo } = estadoCelda(r, k);
    const borra = cls.includes('borra');
    return `<td class="c-celda ${cls}"${titulo ? ` title="${esc(titulo)}"` : ''}><input class="celda" data-k="${esc(k)}" value="${esc(valor(r, k))}" list="dl${j}"${borra ? ' placeholder="(se borra)"' : ''} ${NOFILL}></td>`;
  }).join('');
  let otras = '';
  if (!E.f.otras) {
    const ks = Object.keys(r.tags).filter(k => !c.todas.includes(k));
    otras = `<td class="c-otras" title="${esc(ks.map(k => `${k} = ${r.tags[k]}`).join('\n'))}">${ks.length ? `${ks.length} · ${esc(ks.join(', '))}` : ''}</td>`;
  }
  const url = r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" title="Abrir en la consola de AWS">↗</a>` : '';
  return `<tr data-i="${r._i}"${E.sel.has(r.arn) ? ' class="seleccionada"' : ''}>`
    + `<td class="c-sel"><input type="checkbox" class="sel"${E.sel.has(r.arn) ? ' checked' : ''} aria-label="Seleccionar"></td>`
    + `<td class="c-rec"><div class="rec-nombre"><span title="${esc(r.nombre)}">${esc(r.nombre)}</span>${url}</div><div class="rec-id" title="${esc(r.arn)}">${esc(r.id)}</div></td>`
    + `<td class="c-serv"><b>${esc(r.servicio)}</b><small>${esc(r.tipo)} · ${esc(r.region || 'global')}</small></td>`
    + celdas + otras + '</tr>';
}
function pintarPaginas(paginas) {
  const total = E.visibles.length, desde = total ? E.pagina * E.porPagina + 1 : 0;
  const hasta = Math.min(total, (E.pagina + 1) * E.porPagina);
  $('ePaginas').innerHTML = `<label class="campo-linea">Por página<select id="pPor">${[50, 100, 200].map(v =>
    `<option${v === E.porPagina ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
    <span>${n(desde)}–${n(hasta)} de ${n(total)}</span>
    <button type="button" class="secundario" id="pAnt" ${E.pagina === 0 ? 'disabled' : ''} aria-label="Anterior">‹</button>
    <button type="button" class="secundario" id="pSig" ${E.pagina >= paginas - 1 ? 'disabled' : ''} aria-label="Siguiente">›</button>`;
}
function pintarBarra() {
  const vis = new Set(E.visibles.map(r => r.arn));
  const fuera = [...E.sel].filter(a => !vis.has(a)).length;
  $('eSelInfo').innerHTML = E.sel.size
    ? `<b>${n(E.sel.size)}</b> seleccionados${fuera ? ` (${n(fuera)} fuera del filtro)` : ''} · <button type="button" class="enlace" id="selQuitar">quitar selección</button>`
    : 'Marca recursos para cambiarlos en bloque:';
  $('eBloque').classList.toggle('sin-seleccion', !E.sel.size);
  const c = contarCambios();
  $('ePendientes').textContent = c.total ? `${n(c.total)} cambio${c.total === 1 ? '' : 's'} en ${n(c.recursos)} recurso${c.recursos === 1 ? '' : 's'}` : '';
  $('eRevisar').disabled = !c.total;
  $('eDescartar').hidden = !c.total;
  const todo = $('selTodo');
  if (todo) {
    const marcados = E.visibles.filter(r => E.sel.has(r.arn)).length;
    todo.checked = marcados > 0 && marcados === E.visibles.length;
    todo.indeterminate = marcados > 0 && marcados < E.visibles.length;
  }
}
// Al cambiar el filtro se vuelve a la primera página
function refiltrar() {
  E.pagina = 0;
  pintarSelects();
  pintarCobertura();
  pintarTabla();
}

// ------------------------------------------------------------------ eventos de la tabla
// Editar sin repintar la tabla: solo la celda, la cobertura y la barra (no se pierde el foco)
$('eCuerpo').addEventListener('input', e => {
  const input = e.target.closest('.celda');
  if (!input) return;
  const r = E.recursos[+input.closest('tr').dataset.i], k = input.dataset.k;
  setEdicion(r, k, input.value);
  const td = input.parentElement, { cls, titulo } = estadoCelda(r, k);
  td.className = `c-celda ${cls}`;
  td.title = titulo;
  input.placeholder = cls.includes('borra') ? '(se borra)' : '';
  pintarCobertura();
  pintarBarra();
  guardarBorrador();
});
// Intro o ↓ bajan a la misma columna de la fila siguiente; ↑ sube
$('eCuerpo').addEventListener('keydown', e => {
  const input = e.target.closest('.celda');
  if (!input || !['Enter', 'ArrowDown', 'ArrowUp'].includes(e.key)) return;
  const tr = input.closest('tr');
  const destino = e.key === 'ArrowUp' ? tr.previousElementSibling : tr.nextElementSibling;
  const otra = destino && destino.querySelector(`.celda[data-k="${CSS.escape(input.dataset.k)}"]`);
  if (otra) { e.preventDefault(); otra.focus(); otra.select(); }
});
$('eCuerpo').addEventListener('change', e => {
  if (!e.target.classList.contains('sel')) return;
  const tr = e.target.closest('tr'), r = E.recursos[+tr.dataset.i];
  if (e.target.checked) E.sel.add(r.arn); else E.sel.delete(r.arn);
  tr.classList.toggle('seleccionada', e.target.checked);
  pintarBarra();
});
$('eCabeza').addEventListener('click', e => {
  const b = e.target.closest('button.orden');
  if (!b) return;
  E.orden = { col: b.dataset.col, dir: E.orden.col === b.dataset.col ? -E.orden.dir : 1 };
  pintarTabla();
});
// La casilla de cabecera selecciona TODO lo filtrado, no solo la página
$('eCabeza').addEventListener('change', e => {
  if (e.target.id !== 'selTodo') return;
  const todos = E.visibles.every(r => E.sel.has(r.arn));
  E.visibles.forEach(r => todos ? E.sel.delete(r.arn) : E.sel.add(r.arn));
  pintarTabla();
});
$('ePaginas').addEventListener('click', e => {
  if (e.target.id === 'pAnt') E.pagina--;
  else if (e.target.id === 'pSig') E.pagina++;
  else return;
  pintarTabla();
  $('eCaja').scrollTop = 0;
});
$('ePaginas').addEventListener('change', e => {
  if (e.target.id !== 'pPor') return;
  E.porPagina = +e.target.value;
  E.pagina = 0;
  pintarTabla();
});
$('eBarra').addEventListener('click', e => {
  if (e.target.id !== 'selQuitar') return;
  E.sel.clear();
  pintarTabla();
});

// ------------------------------------------------------------------ filtros
let temporizador = null;
$('fTexto').addEventListener('input', () => {
  clearTimeout(temporizador);
  temporizador = setTimeout(() => { E.f.texto = $('fTexto').value.trim(); refiltrar(); }, 180);
});
for (const [id, k] of [['fServicio', 'servicio'], ['fEntorno', 'entorno']]) {
  $(id).addEventListener('change', () => { E.f[k] = $(id).value; refiltrar(); });
}
for (const [id, k] of [['fAvisos', 'avisos'], ['fCambios', 'cambios'], ['fOtras', 'otras']]) {
  $(id).addEventListener('change', () => { E.f[k] = $(id).checked; refiltrar(); });
}
$('eCobertura').addEventListener('click', e => {
  const b = e.target.closest('.cob');
  if (!b || b.disabled) return;
  E.f.falta = E.f.falta === b.dataset.k ? '' : b.dataset.k;
  refiltrar();
});
$('eActivos').addEventListener('click', e => {
  const q = e.target.closest('[data-quitar]');
  if (!q) return;
  const quitar = q.dataset.quitar === 'todos' ? ['texto', 'falta', 'servicio', 'entorno', 'avisos', 'cambios'] : [q.dataset.quitar];
  for (const k of quitar) E.f[k] = typeof E.f[k] === 'boolean' ? false : '';
  if (quitar.includes('texto')) $('fTexto').value = '';
  refiltrar();
});

// ------------------------------------------------------------------ en bloque
function seleccionados() { return [...E.sel].map(a => E.porArn.get(a)).filter(Boolean); }
function claveBloque() {
  const k = $('bClave').value.trim();
  if (!k) { toast('Escribe la etiqueta.', true); $('bClave').focus(); return null; }
  if (reservada(k)) { toast('Los prefijos aws: y kubernetes.io/ están reservados.', true); return null; }
  if (k.length > MAX_CLAVE) { toast(`La etiqueta pasa de ${MAX_CLAVE} caracteres.`, true); return null; }
  return k;
}
function trasBloque(mensaje) {
  pintarSelects();
  pintarCobertura();
  pintarTabla();
  guardarBorrador();
  toast(mensaje);
}
$('bPoner').addEventListener('click', () => {
  const k = claveBloque();
  if (!k) return;
  const v = $('bValor').value;
  if (!v) { toast('Escribe el valor (para borrar, «Quitar etiqueta»).', true); $('bValor').focus(); return; }
  const rs = seleccionados();
  rs.forEach(r => setEdicion(r, k, v));
  asegurarColumna(k);
  trasBloque(`${k} = ${v} en ${n(rs.length)} recursos (pendiente de revisar).`);
});
$('bQuitar').addEventListener('click', () => {
  const k = claveBloque();
  if (!k) return;
  const rs = seleccionados().filter(r => k in r.tags || (E.ed[r.arn] && k in E.ed[r.arn]));
  rs.forEach(r => setEdicion(r, k, ''));
  asegurarColumna(k);
  trasBloque(rs.length ? `${k} se borra en ${n(rs.length)} recursos (pendiente de revisar).` : `Ninguno de los seleccionados tiene ${k}.`);
});
$('bMinusculas').addEventListener('click', () => {
  let cambios = 0;
  for (const r of seleccionados()) {
    for (const k of cfg().esquema) {
      if (k === 'Name') continue;
      const v = valor(r, k);
      if (v && v !== v.toLowerCase()) { setEdicion(r, k, v.toLowerCase()); cambios++; }
    }
  }
  trasBloque(cambios ? `${n(cambios)} valores pasados a minúscula.` : 'No había mayúsculas en el esquema de lo seleccionado.');
});
$('bClave').addEventListener('input', () => {
  // El valor sugiere el catálogo de la etiqueta escrita
  const j = E.cols.indexOf($('bClave').value.trim());
  if (j >= 0) $('bValor').setAttribute('list', `dl${j}`); else $('bValor').removeAttribute('list');
});
$('eColumna').addEventListener('click', () => {
  modal.abrir(`<h2>Nueva columna</h2><p>Una etiqueta que todavía no está en la tabla. Rellena las celdas que quieras: las vacías no se tocan.</p>
    <label class="campo campo-modal">Etiqueta<input id="cNueva" ${NOFILL}></label>
    <div class="acciones"><button type="button" class="primario" id="cAnadir">Añadir</button><button type="button" class="secundario" id="cCancelar">Cancelar</button></div>`);
  $('cNueva').focus();
  const anadir = () => {
    const k = $('cNueva').value.trim();
    if (!k) return;
    if (reservada(k)) { toast('Los prefijos aws: y kubernetes.io/ están reservados.', true); return; }
    if (k.length > MAX_CLAVE) { toast(`Pasa de ${MAX_CLAVE} caracteres.`, true); return; }
    if (columnas().todas.includes(k)) { toast(`${k} ya está en la tabla.`); modal.cerrar(); return; }
    E.extras.push(k);
    modal.cerrar();
    pintarSelects();
    pintarTabla();
    guardarBorrador();
    const celda = $('eCuerpo').querySelector(`.celda[data-k="${CSS.escape(k)}"]`);
    if (celda) celda.scrollIntoView({ block: 'nearest', inline: 'center' });
  };
  $('cAnadir').onclick = anadir;
  $('cCancelar').onclick = modal.cerrar;
  $('cNueva').addEventListener('keydown', e => { if (e.key === 'Enter') anadir(); });
});
$('eDescartar').addEventListener('click', () => {
  const c = contarCambios();
  modal.abrir(`<h2>Descartar cambios</h2><p>Se pierden ${n(c.total)} cambios en ${n(c.recursos)} recursos. AWS no se ha tocado.</p>
    <div class="acciones"><button type="button" class="primario peligro" id="dSi">Descartar</button><button type="button" class="secundario" id="dNo">Cancelar</button></div>`);
  $('dSi').onclick = () => { E.ed = {}; guardarBorrador(); modal.cerrar(); refiltrar(); };
  $('dNo').onclick = modal.cerrar;
});

// ------------------------------------------------------------------ revisar y aplicar
function itemsPendientes() {
  return Object.entries(E.ed).map(([arn, cambios]) => {
    const r = E.porArn.get(arn), base = {};
    for (const k in cambios) base[k] = r && k in r.tags ? r.tags[k] : null;
    return { arn, cambios, base };
  });
}
$('eRevisar').addEventListener('click', () => revisar(itemsPendientes()));

const sv = v => v == null ? `<span class="sin-valor">${SIN_VALOR}</span>` : esc(v);
function filaPlan(p) {
  const chips = [
    ...Object.entries(p.crear).map(([k, v]) => `<span class="pill crear">+ ${esc(k)} = ${esc(v)}</span>`),
    ...Object.entries(p.cambiar).map(([k, [a, b]]) => `<span class="pill cambiar">${esc(k)}: <del>${esc(a)}</del> → ${esc(b)}</span>`),
    ...Object.entries(p.borrar).map(([k, a]) => `<span class="pill borrar">− ${esc(k)} <del>${esc(a)}</del></span>`),
  ];
  const lineas = [
    ...p.conflictos.map(c => `<p class="linea-plan error"><span class="pill conflicto">Conflicto</span> ${esc(c.clave)}: al leer era ${sv(c.leido)}, ahora en AWS es ${sv(c.ahora)}. No se toca.</p>`),
    ...p.errores.map(e => `<p class="linea-plan error">${p.estado === 'error' ? 'No se aplica: ' : ''}${esc(e)}</p>`),
    ...p.avisos.map(a => `<p class="linea-plan warn">Aviso: ${esc(a)}</p>`),
  ];
  const cls = p.estado === 'error' ? ' mal' : p.conflictos.length ? ' conflicto' : '';
  return `<div class="plan-fila${cls}"><div class="plan-cab"><b>${esc(p.nombre || p.arn.split(/[:/]/).pop())}</b><code>${esc(p.arn)}</code></div>
    ${chips.length ? `<div class="chips">${chips.join('')}</div>` : ''}${lineas.join('')}</div>`;
}
async function revisar(items, opciones = {}) {
  const titulo = opciones.titulo || 'Revisar cambios';
  modal.abrir(`<h2>${esc(titulo)}</h2><p><span class="girando en-linea"></span> Releyendo de AWS lo que hay ahora en estos ${n(items.length)} recursos…</p>`);
  try {
    const res = await post('/api/plan', { items });
    pintarPlan(res, items, { ...opciones, titulo });
  } catch (e) {
    modal.abrir(`<h2>${esc(titulo)}</h2><div class="aviso mal">${esc(e.message)}</div>`);
  }
}
function pintarPlan(res, items, opciones) {
  const r = res.resumen, plan = res.plan;
  const conAlgo = plan.filter(p => p.estado !== 'nada');
  const nada = plan.length - conAlgo.length;
  const pills = [
    `<span class="pill cuenta">${n(r.recursos)} recurso${r.recursos === 1 ? '' : 's'}</span>`,
    r.crear ? `<span class="pill crear">+${n(r.crear)} crear</span>` : '',
    r.cambiar ? `<span class="pill cambiar">~${n(r.cambiar)} cambiar</span>` : '',
    r.borrar ? `<span class="pill borrar">−${n(r.borrar)} borrar</span>` : '',
    r.conflictos ? `<span class="pill conflicto">${n(r.conflictos)} conflicto${r.conflictos === 1 ? '' : 's'}</span>` : '',
    r.errores ? `<span class="pill cuenta mal">${n(r.errores)} con errores</span>` : '',
    r.avisos ? `<span class="pill cuenta aviso">${n(r.avisos)} aviso${r.avisos === 1 ? '' : 's'}</span>` : '',
  ].join('');
  const confirmacion = `APLICAR EN ${res.account}`;
  modal.abrir(`<h2>${esc(opciones.titulo)}</h2>
    <p>Comparado con AWS <b>ahora mismo</b> · cuenta <b>${esc(res.account)}</b> · perfil ${esc(res.perfil_aws || 'por defecto')}</p>
    <div class="resumen-plan">${pills}</div>
    ${nada ? `<p>${n(nada)} recurso${nada === 1 ? '' : 's'} ya estaba${nada === 1 ? '' : 'n'} así en AWS: nada que hacer.</p>` : ''}
    <div class="plan">${conAlgo.map(filaPlan).join('') || '<p class="vacio">No hay nada que aplicar.</p>'}</div>
    ${r.conflictos ? `<p><button type="button" class="enlace" id="cBase">Tomar lo que hay ahora en AWS como punto de partida y revisar otra vez</button></p>` : ''}
    ${r.recursos ? `<div class="confirmar">
      <label><span>Para aplicar escribe <code>${esc(confirmacion)}</code></span><input id="cConfirmar" ${NOFILL}></label>
      <div class="acciones"><button type="button" class="primario" id="cAplicar" disabled>Aplicar en AWS</button><button type="button" class="secundario" id="cCancelar">Cancelar</button></div>
    </div>` : `<div class="acciones"><button type="button" class="secundario" id="cCancelar">Cerrar</button></div>`}`);
  $('cCancelar').onclick = modal.cerrar;
  if ($('cBase')) $('cBase').onclick = () => tomarBase(plan, items, opciones);
  if (!$('cConfirmar')) return;
  $('cConfirmar').focus();
  $('cConfirmar').addEventListener('input', () => { $('cAplicar').disabled = $('cConfirmar').value.trim() !== confirmacion; });
  $('cConfirmar').addEventListener('keydown', e => { if (e.key === 'Enter' && !$('cAplicar').disabled) $('cAplicar').click(); });
  $('cAplicar').onclick = () => aplicarCambios(items, $('cConfirmar').value.trim(), opciones);
}
// Un conflicto: alguien cambió la etiqueta en AWS desde que se leyó. Se toma lo de AWS como
// nuevo punto de partida (sin perder lo editado) y se revisa otra vez.
function tomarBase(plan, items, opciones) {
  for (const p of plan) {
    const r = E.porArn.get(p.arn);
    for (const c of p.conflictos) {
      if (r) { if (c.ahora == null) delete r.tags[c.clave]; else r.tags[c.clave] = c.ahora; }
      const it = items.find(i => i.arn === p.arn);
      if (it) it.base[c.clave] = c.ahora;
    }
  }
  revisar(opciones.deshace ? items : itemsPendientes(), opciones);
}
async function aplicarCambios(items, confirmacion, opciones) {
  $('cAplicar').disabled = true;
  $('cAplicar').textContent = 'Aplicando…';
  let res;
  try {
    res = await post('/api/aplicar', { items, confirmacion, deshace: opciones.deshace || null });
  } catch (e) {
    toast(e.message, true);
    $('cAplicar').disabled = false;
    $('cAplicar').textContent = 'Aplicar en AWS';
    return;
  }
  // Lo que AWS aceptó pasa a ser el valor leído; lo que ya estaba así, también
  for (const p of res.plan) {
    const r = E.porArn.get(p.arn), it = items.find(i => i.arn === p.arn);
    if (!r || !it) continue;
    for (const k of p.sin_cambio) { const v = it.cambios[k]; if (v == null) delete r.tags[k]; else r.tags[k] = v; }
  }
  for (const x of res.resultados) {
    const r = E.porArn.get(x.arn);
    if (!r) continue;
    for (const [k, v] of Object.entries(x.despues)) {
      if (v == null) delete r.tags[k]; else { r.tags[k] = v; if (!E.datos.claves.includes(k)) E.datos.claves.push(k); }
      if (k === 'Name') r.nombre = v || r.id.split('/').pop();
    }
  }
  items.forEach(it => limpiarEdiciones(it.arn));
  guardarBorrador();
  pintarTodo();
  if (window.cargarHistorial) window.cargarHistorial();

  const ok = res.resultados.filter(x => x.estado === 'aplicado').length;
  const malos = res.resultados.filter(x => x.estado !== 'aplicado');
  modal.abrir(`<h2>${malos.length ? 'Aplicado con errores' : 'Aplicado'}</h2>
    <div class="resumen-plan"><span class="pill cuenta ok">${n(ok)} recurso${ok === 1 ? '' : 's'} aplicado${ok === 1 ? '' : 's'}</span>
    ${malos.length ? `<span class="pill cuenta mal">${n(malos.length)} con errores</span>` : ''}</div>
    ${malos.length ? `<div class="plan">${malos.map(x => `<div class="plan-fila mal"><div class="plan-cab"><b>${esc(E.porArn.get(x.arn)?.nombre || x.arn)}</b><code>${esc(x.arn)}</code></div>
      ${x.errores.map(e => `<p class="linea-plan error">${esc(e)}</p>`).join('')}${x.estado === 'parcial' ? '<p class="linea-plan warn">Una parte sí se aplicó (está en el historial).</p>' : ''}</div>`).join('')}</div>
      <p>AWS puede responder 200 sin aplicar (recurso borrado, sin permisos…): lo que falló sigue pendiente en la tabla.</p>` : ''}
    ${res.lote ? `<p>Guardado en el historial como el lote <code>${esc(res.lote)}</code>: desde ahí se puede deshacer.</p>` : ''}
    <div class="acciones"><button type="button" class="primario" id="cVale">Vale</button>${res.lote ? '<a class="enlace" href="#/historial" id="cHist">Ver el historial</a>' : ''}</div>`);
  $('cVale').onclick = modal.cerrar;
  if ($('cHist')) $('cHist').onclick = modal.cerrar;
}
window.revisar = revisar;

// ------------------------------------------------------------------ leer, importar, cargar
function ponerDatos(datos) {
  E.datos = datos;
  E.recursos = datos ? datos.recursos : [];
  E.recursos.forEach((r, i) => { r._i = i; });
  E.porArn = new Map(E.recursos.map(r => [r.arn, r]));
  E.sel = new Set([...E.sel].filter(a => E.porArn.has(a)));
  $('eVacio').hidden = !!datos;
  $('eTrabajo').hidden = !datos;
  $('eExportar').hidden = $('eExportarCsv').hidden = !datos;
}
async function cargarInventario() {
  const { datos } = await api('/api/inventario');
  ponerDatos(datos);
  if (!datos) return;
  recuperarBorrador();
  Object.keys(E.ed).forEach(limpiarEdiciones);
  pintarTodo();
}
async function leer(todos) {
  $('eAviso').hidden = true;
  try {
    await post('/api/leer', { todos: !!todos });
  } catch (e) {
    const errores = (e.datos && e.datos.errores) || [];
    $('eAviso').innerHTML = `${esc(e.message)}${errores.length ? ` ${errores.map(esc).join(' ')}` : ''} <a href="#/ajustes">Ajustes</a>`;
    $('eAviso').className = 'aviso mal';
    $('eAviso').hidden = false;
    return;
  }
  $('eLectura').hidden = false;
  $('eLeer').disabled = $('eLeerVacio').disabled = true;
  const sondear = async () => {
    let estado;
    try { estado = await api('/api/leer'); } catch (e) { estado = { activa: false, error: e.message, mensajes: [] }; }
    $('eLecturaLog').textContent = estado.mensajes.join('\n');
    $('eLecturaLog').scrollTop = $('eLecturaLog').scrollHeight;
    if (estado.activa) { setTimeout(sondear, 700); return; }
    $('eLectura').hidden = true;
    $('eLeer').disabled = $('eLeerVacio').disabled = false;
    if (estado.error) {
      $('eAviso').textContent = `No se pudo leer: ${estado.error}`;
      $('eAviso').className = 'aviso mal';
      $('eAviso').hidden = false;
      return;
    }
    const avisos = estado.mensajes.filter(m => m.startsWith('Aviso'));
    if (avisos.length) {
      $('eAviso').innerHTML = `${n(avisos.length)} aviso${avisos.length === 1 ? '' : 's'} al leer (permisos o servicios no disponibles): <details><summary>ver</summary><pre>${esc(avisos.join('\n'))}</pre></details>`;
      $('eAviso').className = 'aviso';
      $('eAviso').hidden = false;
    }
    await cargarInventario();
    refrescarEstado();
    toast(`Leído: ${n(E.recursos.length)} recursos.`);
  };
  sondear();
}
$('eLeer').addEventListener('click', () => leer(false));
$('eLeerVacio').addEventListener('click', () => leer($('eTodos').checked));
$('eImportar').addEventListener('click', () => $('eFichero').click());
$('eFichero').addEventListener('change', async () => {
  const fichero = $('eFichero').files[0];
  $('eFichero').value = '';
  if (!fichero) return;
  const fd = new FormData();
  fd.append('fichero', fichero);
  try {
    const res = await api('/api/importar', { method: 'POST', body: fd });
    let total = 0;
    for (const [arn, cambios] of Object.entries(res.cambios)) {
      const r = E.porArn.get(arn);
      if (!r) continue;
      for (const [k, v] of Object.entries(cambios)) { setEdicion(r, k, v ?? ''); asegurarColumna(k); total++; }
    }
    $('eAviso').hidden = !res.avisos.length;
    $('eAviso').className = 'aviso';
    $('eAviso').innerHTML = res.avisos.map(esc).join('<br>');
    guardarBorrador();
    refiltrar();
    toast(total ? `${fichero.name}: ${n(total)} cambios en ${n(Object.keys(res.cambios).length)} recursos, pendientes de revisar.` : `${fichero.name}: coincide con el inventario, nada que cambiar.`);
  } catch (e) {
    toast(e.message, true);
  }
});
TX.oyentes.push(() => { if (E.datos) pintarTodo(); });
