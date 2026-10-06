// Simula la página de compra de PuntoTicket: lista de precios, SVG de sectores y
// asientos que se dibujan en dos tandas después del click (como una carga AJAX).
function armarCompra(cfg) {
  document.getElementById('fecha').textContent = cfg.fecha;
  const ul = document.getElementById('lista');
  cfg.lista.forEach(s => {
    ul.insertAdjacentHTML('beforeend',
      `<li class="sector" data-id_sector="${s.id}"><span class="circulo--map" style="background-color:${s.color}"></span>${s.nombre} $${s.precio} ${s.estado || ''}</li>`);
  });
  const svg = document.getElementById('svg');
  cfg.svg.forEach((s, i) => {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    p.setAttribute('id', s.id);
    p.setAttribute('class', 'interactive-sector' + (s.noDisp ? ' no_disponible' : ''));
    p.setAttribute('fill', s.fill || '#B9B7BD');
    p.setAttribute('x', 10 * i); p.setAttribute('width', 8); p.setAttribute('height', 8);
    p.addEventListener('click', () => {
      const cont = document.querySelector('.contenedor_filas_asientos');
      if (!s.asientos) return;  // sector general: no dibuja asientos
      setTimeout(() => {
        const dibujar = (desde, hasta) => {
          let html = '<ul>';
          for (let k = desde; k < hasta; k++) {
            const cls = k < s.vendidos ? 'asiento notvacant' : 'asiento';
            html += `<li class="${cls}" id="${s.id}-a${k}"></li>`;
          }
          cont.insertAdjacentHTML('beforeend', html + '</ul>');
        };
        const mitad = Math.floor(s.asientos / 2);
        dibujar(0, mitad);
        setTimeout(() => dibujar(mitad, s.asientos), 400);
      }, 300);
    });
    svg.appendChild(p);
  });
}
