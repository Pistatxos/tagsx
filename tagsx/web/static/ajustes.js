// Ajustes: perfil de AWS, regiones, servicios, esquema y catálogos. Se guardan en el mismo
// ~/.xsoft/tagsx_config.py que lee la terminal.
'use strict';
const A = { perfiles: [], regiones: [], form: null, sucio: false };

function formDesdeConfig(c) {
  return {
    perfil_aws: c.perfil_aws || '',
    regiones: [...(c.regiones || [])],
    servicios: [...(c.servicios || [])],
    esquema: (c.esquema || []).map(k => ({ clave: k, catalogo: ((c.catalogos || {})[k] || []).join(', ') })),
    minusculas: c.minusculas !== false,
    // Los catálogos de etiquetas que no están en el esquema se conservan tal cual
    otrosCatalogos: Object.fromEntries(Object.entries(c.catalogos || {}).filter(([k]) => !(c.esquema || []).includes(k))),
  };
}
function configDesdeForm() {
  const f = A.form, catalogos = { ...f.otrosCatalogos };
  const esquema = [];
  for (const fila of f.esquema) {
    const k = fila.clave.trim();
    if (!k) continue;
    esquema.push(k);
    const valores = fila.catalogo.split(',').map(v => v.trim()).filter(Boolean);
    if (valores.length) catalogos[k] = valores; else delete catalogos[k];
  }
  return { perfil_aws: f.perfil_aws, regiones: f.regiones, servicios: f.servicios, esquema, catalogos, minusculas: f.minusculas };
}

function pintarAjustes() {
  const e = TX.estado, f = A.form;
  $('aFichero').textContent = e.config_path_corto;
  $('aAviso').hidden = !e.error_lectura && e.existe;
  $('aAviso').className = e.error_lectura ? 'aviso mal' : 'aviso';
  $('aAviso').textContent = e.error_lectura
    ? `No se puede leer la configuración: ${e.error_lectura}`
    : 'Todavía no hay fichero de configuración: esto es la plantilla. Al guardar se crea.';

  const perfiles = [...new Set(['', ...A.perfiles, f.perfil_aws])];
  $('aPerfil').innerHTML = perfiles.map(p => `<option value="${esc(p)}"${p === f.perfil_aws ? ' selected' : ''}>${p ? esc(p) : '(por defecto / AWS_PROFILE)'}</option>`).join('');

  const regiones = [...new Set([...A.regiones, ...f.regiones])];
  $('aRegiones').innerHTML = regiones.map(r => `<button type="button" class="chip-sel${f.regiones.includes(r) ? ' activo' : ''}" data-region="${esc(r)}" aria-pressed="${f.regiones.includes(r)}">${esc(r)}</button>`).join('');

  $('aServicios').innerHTML = e.detectables.map(s => `<label class="check"><input type="checkbox" data-servicio="${esc(s)}"${f.servicios.includes(s) ? ' checked' : ''}>
    <span>${esc(s)}${e.globales.includes(s) ? ' <small>global</small>' : ''}</span></label>`).join('');
  $('aNoDetectables').textContent = `Sin escáner todavía (solo se ven si ya tienen alguna etiqueta): ${e.no_detectables.join(', ')}.`;

  pintarEsquema();
  $('aMinusculas').checked = f.minusculas;
}
function pintarEsquema() {
  const filas = A.form.esquema;
  $('aEsquema').innerHTML = filas.map((fila, i) => `<tr data-i="${i}">
    <td><input class="clave-in" data-campo="clave" value="${esc(fila.clave)}" ${NOFILL}></td>
    <td><input data-campo="catalogo" value="${esc(fila.catalogo)}" placeholder="${fila.clave === 'Name' ? 'libre' : 'valor1, valor2…'}" ${NOFILL}></td>
    <td><div class="mover"><button type="button" class="subir" data-mover="-1" ${i === 0 ? 'disabled' : ''} aria-label="Subir">↑</button>
      <button type="button" class="subir" data-mover="1" ${i === filas.length - 1 ? 'disabled' : ''} aria-label="Bajar">↓</button>
      <button type="button" class="quitar" aria-label="Quitar">×</button></div></td></tr>`).join('');
}
function sucio() { A.sucio = true; $('aEstado').textContent = 'Cambios sin guardar.'; }

$('aPerfil').addEventListener('change', () => { A.form.perfil_aws = $('aPerfil').value; $('aProbarRes').textContent = ''; sucio(); });
$('aRegiones').addEventListener('click', e => {
  const b = e.target.closest('[data-region]');
  if (!b) return;
  const r = b.dataset.region, lista = A.form.regiones;
  A.form.regiones = lista.includes(r) ? lista.filter(x => x !== r) : [...lista, r];
  b.classList.toggle('activo');
  b.setAttribute('aria-pressed', A.form.regiones.includes(r));
  sucio();
});
$('aServicios').addEventListener('change', e => {
  const s = e.target.dataset.servicio;
  if (!s) return;
  A.form.servicios = e.target.checked ? [...A.form.servicios, s] : A.form.servicios.filter(x => x !== s);
  sucio();
});
$('aServTodos').addEventListener('click', () => { A.form.servicios = [...TX.estado.detectables]; pintarAjustes(); sucio(); });
$('aServNinguno').addEventListener('click', () => { A.form.servicios = []; pintarAjustes(); sucio(); });
$('aEsquema').addEventListener('input', e => {
  const tr = e.target.closest('tr');
  if (!tr || !e.target.dataset.campo) return;
  A.form.esquema[+tr.dataset.i][e.target.dataset.campo] = e.target.value;
  sucio();
});
$('aEsquema').addEventListener('click', e => {
  const tr = e.target.closest('tr');
  if (!tr) return;
  const i = +tr.dataset.i, filas = A.form.esquema;
  if (e.target.classList.contains('quitar')) { filas.splice(i, 1); }
  else if (e.target.dataset.mover) {
    const j = i + +e.target.dataset.mover;
    [filas[i], filas[j]] = [filas[j], filas[i]];
  } else return;
  pintarEsquema();
  sucio();
});
$('aEtiquetaNueva').addEventListener('click', () => {
  A.form.esquema.push({ clave: '', catalogo: '' });
  pintarEsquema();
  $('aEsquema').querySelector('tr:last-child .clave-in').focus();
  sucio();
});
$('aMinusculas').addEventListener('change', () => { A.form.minusculas = $('aMinusculas').checked; sucio(); });

$('aProbar').addEventListener('click', async () => {
  $('aProbarRes').textContent = 'Probando…';
  $('aProbarRes').className = 'probar-res';
  try {
    const c = await post('/api/aws/probar', { perfil_aws: A.form.perfil_aws });
    $('aProbarRes').textContent = `Cuenta ${c.account} · ${c.arn.split(':').slice(5).join(':')}`;
  } catch (e) {
    $('aProbarRes').textContent = e.message;
    $('aProbarRes').className = 'probar-res error';
  }
});

$('aGuardar').addEventListener('click', async () => {
  $('aErrores').hidden = true;
  try {
    TX.estado = await api('/api/config', { method: 'PUT', body: JSON.stringify({ config: configDesdeForm() }) });
    A.sucio = false;
    A.form = formDesdeConfig(TX.estado.config);
    TX.oyentes.forEach(f => f(TX.estado));
    $('aEstado').textContent = 'Guardado.';
    toast('Ajustes guardados.');
  } catch (e) {
    const lista = [...((e.datos && e.datos.errores) || [])];
    $('aErrores').innerHTML = `<ul>${(lista.length ? lista : [e.message]).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
    $('aErrores').hidden = false;
    $('aEstado').textContent = '';
  }
});

TX.oyentes.push(estado => {
  if (!estado.config || A.sucio) return;
  A.form = formDesdeConfig(estado.config);
  pintarAjustes();
});

// ------------------------------------------------------------------ arranque
(async () => {
  mostrarVista();
  try {
    const p = await api('/api/aws/perfiles');
    A.perfiles = p.perfiles;
    A.regiones = p.regiones;
  } catch { /* sin perfiles: se puede escribir en el fichero */ }
  try {
    await refrescarEstado();
    await cargarInventario();
  } catch (e) {
    toast(e.message, true);
  }
})();
