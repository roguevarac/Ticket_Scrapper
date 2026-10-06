# Ticket_Scrapper: reporte de Música de PuntoTicket

Lee todos los eventos de https://www.puntoticket.com/musica y arma un Excel con:

- **Una fila por función**: cada fecha (y hora) de un evento es un evento aparte.
  Columnas: evento, fecha, día, hora, lugar, estado, agotado (SI/NO).
- **Ocupación real**: entra a la página de compra de cada función, recorre los
  sectores del mapa y cuenta los asientos vendidos y libres.
- **Sectores agotados**: no muestran asientos, así que se cuentan 100% vendidos
  con la capacidad que tenían la última vez que se leyeron (historial).
- **Cancha / general**: PuntoTicket no muestra cuántas entradas quedan, solo si
  está disponible, casi agotada o agotada. Si cargás el aforo del recinto se
  estima la cancha como `aforo - asientos numerados`.

## Instalación (una vez)

```bat
pip install -r requirements.txt
playwright install chromium
```

## Uso

1. Abrí Chrome con depuración remota: doble click en `abrir_chrome.bat`.
2. En ese Chrome entrá a puntoticket.com e iniciá sesión (la página de compra la pide).
3. En una consola, dentro de esta carpeta:

```bat
python scraper_puntoticket.py
```

El reporte queda en `reportes\puntoticket_musica_AAAAMMDD_HHMM.xlsx` (y dos CSV
con lo mismo). Se va guardando después de cada evento, así que si se corta no se
pierde lo avanzado.

Opciones útiles:

| Opción | Para qué |
|---|---|
| `--solo aitana --solo "paulo londra"` | Procesar solo esos eventos (prueba rápida). |
| `--limite 5` | Solo los primeros 5 eventos del catálogo. |
| `--sin-asientos` | Solo fechas y estados, sin entrar a los sectores (mucho más rápido). |
| `--debug` | Guarda HTML y captura de cada página de compra en `reportes\debug` para revisar casos raros. |
| `--lanzar` | Abre un Chromium propio en vez de usar el Chrome de `abrir_chrome.bat`. La sesión queda guardada en `perfil_chrome`. |
| `--espera-cola 180` | Más tiempo en la sala de espera (queue) de eventos con mucha demanda. |

## El Excel

| Hoja | Contenido |
|---|---|
| **Funciones** | Una fila por función, con % de ocupación numerada, % total estimado, sectores de cancha y nivel de confianza. |
| **Sectores** | Detalle por sector: asientos medidos, capacidad usada y de dónde salió. |
| **Alertas** | Casos para revisar a mano (sala de espera que no soltó, sector sin nombre, fecha no interpretada…). |
| **Notas** | Cómo se calcula cada columna. |

### Cómo se decide la capacidad de un sector agotado

Con la planilla del 04-08-2026 se vio que el mismo `sector_id` en el mismo
recinto cambia de capacidad entre eventos (Movistar Arena `TT2S1`: 72, 90, 144,
234 o 288 según el montaje), pero nunca dentro de la misma función. Por eso se
busca en este orden:

1. `HISTORIAL_FUNCION`: misma función, lectura anterior.
2. `HISTORIAL_EVENTO`: mismo evento, otra fecha.
3. `REF_RECINTO`: mismo recinto en otros eventos (mediana). Es aproximado.

El historial está en `data/historial_sectores.csv`; cada corrida le agrega lo
que midió. Ya trae las 806 lecturas de la planilla `EVENTOS_AVANCE_04082026.xlsx`.
**Conviene correrlo seguido**: si un sector se lee antes de agotarse, después su
capacidad sale exacta. Para cargar otra planilla vieja:

```bat
python herramientas\importar_planilla.py MI_PLANILLA.xlsx
```

### Estimación de la cancha

Completá `aforo_total` en `data/aforo_recintos.csv` (por ejemplo, el aforo de
Movistar Arena con cancha de pie). Con eso el reporte calcula:

- `Cancha estimada = aforo - asientos numerados de esa función`.
- `% ocupación total (estim.)` cuando la cancha está agotada (o 100% si toda la
  función está agotada).

Si el recinto no tiene aforo cargado, esas columnas quedan vacías.

### Estado de la función

- Manda lo que se ve en la **página de compra**: si todos los sectores están
  agotados, la función está agotada. La columna "Estado en landing" guarda lo
  que decía la página del evento, porque a veces dice AGOTADO y en la compra hay
  entradas (caso Anuel).
- Si no hay link de compra se usa lo que diga la landing o el catálogo.

## Revisar un sector a mano

Con un sector abierto en Chrome, F12 → Consola → pegar
`herramientas/contar_sector_consola.js`. Sirve para comparar con el reporte.

## Pruebas

```bat
python -m pytest -q
```

Corren contra un sitio local (`tests/sitio`) que imita el HTML de PuntoTicket:
catálogo con "ver más", los templates de landing conocidos (Aitana, Karol G,
Jamiroquai/Anuel, Jeff Mills), sala de espera, mapa SVG con asientos que se
dibujan en dos tandas, sectores agotados y cancha general.

## Estructura

```
scraper_puntoticket.py      punto de entrada
puntoticket/catalogo.py     tarjetas de /musica
puntoticket/landing.py      funciones (fechas) y links de compra de cada evento
puntoticket/compra.py       sala de espera, sectores del mapa y asientos
puntoticket/capacidades.py  historial y capacidad de sectores agotados
puntoticket/resumen.py      ocupación por función
puntoticket/excel.py        reporte
data/                       historial y aforos
```
