// Historial: un lote por cada «Aplicar», con antes y después de cada etiqueta tocada.
// «Deshacer este lote» pasa por el mismo camino: revisar contra AWS (conflictos) y aplicar.
'use strict';
const H = { lotes: [] };

function valorLote(v) { return v == null ? '<span class="sin-valor">(sin valor)</span>' : `<code>${esc(v)}</code>`; }

function pintarLotes() {
  if (!H.lotes.length) {
    $('hLotes').innerHTML = '<p class="vacio">Todavía no se ha aplicado nada desde tagsx en este equipo.</p>';
    return;
  }
  const deshechoPor = {};
  for (const l of H.lotes) if (l.deshace) deshechoPor[l.deshace] = l.id;
  $('hLotes').innerHTML = H.lotes.map(l => {
    const etiquetas = l.cambios.reduce((t, c) => t + Object.keys(c.despues).length, 0);
    const errores = (l.errores || []).length;
    const pills = [
      `<span class="pill cuenta">${n(l.cambios.length)} recurso${l.cambios.length === 1 ? '' : 's'} · ${n(etiquetas)} etiqueta${etiquetas === 1 ? '' : 's'}</span>`,
      errores ? `<span class="pill cuenta mal">${n(errores)} con errores</span>` : '',
      l.deshace ? `<span class="pill cambiar">deshace ${esc(l.deshace)}</span>` : '',
      deshechoPor[l.id] ? `<span class="pill cuenta aviso">deshecho por ${esc(deshechoPor[l.id])}</span>` : '',
    ].join('');
    const filas = l.cambios.flatMap(c => Object.keys(c.despues).map(k => `<tr>
      <td class="c-arn"><code>${esc(c.arn)}</code></td><td class="c-k"><b>${esc(k)}</b></td>
      <td>${valorLote(c.antes[k])} → ${valorLote(c.despues[k])}</td></tr>`)).join('');
    const errFilas = (l.errores || []).map(e => `<tr><td class="c-arn"><code>${esc(e.arn)}</code></td><td colspan="2" class="error">${esc(e.errores.join('; '))}</td></tr>`).join('');
    return `<details class="lote" data-id="${esc(l.id)}">
      <summary><span class="lote-fecha">${esc(fecha(l.fecha))}</span><span class="lote-id">${esc(l.id)}</span>
        <span class="muted">${esc(l.origen)} · cuenta ${esc(l.cuenta)}${l.perfil ? ` · ${esc(l.perfil)}` : ''}</span>${pills}</summary>
      <div class="lote-cuerpo">
        <div class="acciones"><button type="button" class="secundario deshacer" ${l.cambios.length ? '' : 'disabled'}>Deshacer este lote</button></div>
        <table class="tabla-lote"><thead><tr><th class="c-arn">Recurso</th><th class="c-k">Etiqueta</th><th>Antes → después</th></tr></thead>
        <tbody>${filas}${errFilas}</tbody></table>
      </div></details>`;
  }).join('');
}

async function cargarHistorial() {
  try {
    H.lotes = (await api('/api/historial')).lotes;
    pintarLotes();
  } catch (e) {
    $('hLotes').innerHTML = `<div class="aviso mal">${esc(e.message)}</div>`;
  }
}
window.cargarHistorial = cargarHistorial;

$('hLotes').addEventListener('click', async e => {
  const b = e.target.closest('.deshacer');
  if (!b) return;
  const id = b.closest('.lote').dataset.id;
  try {
    const res = await api(`/api/historial/${encodeURIComponent(id)}/deshacer`);
    revisar(res.items, { deshace: id, titulo: `Deshacer el lote ${id}` });
  } catch (err) {
    toast(err.message, true);
  }
});
window.addEventListener('vista', e => { if (e.detail === 'historial') cargarHistorial(); });
