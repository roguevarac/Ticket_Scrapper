// Pegar en la consola de Chrome (F12) con un sector abierto para contar sus asientos a mano
// y comparar con lo que trae el reporte.
const sectorID = 1; // Sector actual

// Asientos verdaderamente disponibles (tienen .asiento, pero NO .notvacant ni .selected)
const disponibles = document.querySelectorAll('.contenedor_filas_asientos ul li.asiento:not(.notvacant):not(.selected)').length;

// Asientos vendidos / ocupados
const ocupados = document.querySelectorAll('.contenedor_filas_asientos ul li.asiento.notvacant').length;

// Asientos en tu carrito temporal
const seleccionados = document.querySelectorAll('.contenedor_filas_asientos ul li.asiento.selected').length;

console.log(`--- SECTOR ${sectorID} ---`);
console.log(`Disponibles: ${disponibles}`);
console.log(`Vendidos / Ocupados: ${ocupados}`);
console.log(`Total en tu selección: ${seleccionados}`);
console.log(`Total Asientos del Sector: ${disponibles + ocupados + seleccionados}`);