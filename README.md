# Corbatul Twin · E70_OMEGA

Gemelo digital del simulador **CORBATUL** (8.º Torneo ACBSP-CompanyGame 2026) con **optimizador**, **simulador de decisiones (what-if)**, **simulación Monte Carlo en tiempo real** y la app web *Corbatul Twin · Modelo de decisión*.

```
corbatul/
  twin.py         Gemelo digital (Año 0 real, costes, demanda, finanzas, balance) + Optimizer
  montecarlo.py   Monte Carlo del plan de una ronda (generador de eventos en streaming)
  server.py       Servidor local (solo biblioteca estándar): sirve la app y emite el Monte Carlo por SSE
  simulador.py    Simulación determinista del plan ajustado (P&G, balance, ratios) y comparación con el plan
  plan.py         Carga el plan (JSON), valida los límites del simulador y lo convierte en decisiones del gemelo
data/
  plan_r1.json    Decisiones de la Ronda 1 + demanda del presupuesto (pesimista / base / optimista)
  muestra_mc.json Muestra de 5.000 simulaciones (la app la muestra si no hay servidor)
  muestra_sim.json Resultados del plan sin ajustes (la app los muestra si no hay servidor)
web/index.html    App web (un solo archivo, sin dependencias): mapa del modelo + datos + Monte Carlo
tests/            Pruebas (unittest)
```

## Inicio rápido

```bash
pip install -r requirements.txt        # numpy y scipy
python -m corbatul.server              # http://localhost:8765
```

o `./run.sh` (macOS/Linux) / `run.bat` (Windows). Abre la app, pulsa **Datos**. Dos tarjetas nuevas: **Simulador de decisiones** y **Simulación Monte Carlo**.

### Simulador de decisiones
Reproduce las pestañas del simulador (1 Precio y ventas · 2 Promoción · 3 Producto · 4 Producción · 5 Financiación · 6 Inversiones financieras · 7 Proyectos). Al mover cualquier precio, promoción, gama, diseño, materia prima, ampliación, unidades, mantenimiento, plazos, préstamos, inversiones o proyectos, se recalcula al instante: resultado neto, ingresos, ROE, efectivo, inventario, índice de valor (proxy) y, debajo, cuenta de resultados, balance, ratios y detalle por producto, siempre frente al plan (Δ). Los valores respetan los límites del simulador (precio ±15 %, gama, rangos…) y avisan si no. **Restablecer plan** vuelve a los valores de la R1.

### Monte Carlo
Pulsa **Monte Carlo ›** (o abre la tarjeta): usa los mismos ajustes. Arranca sola y el histograma, los percentiles y las probabilidades se actualizan en vivo (≈ 1.000 simulaciones por segundo). *Nota:* los ajustes de la versión anterior de esta guía (`precio=a,b,c`…) siguen funcionando como atajos.

También funciona abriendo `web/index.html` directamente desde el disco (`file://`): la app se conecta a `http://localhost:8765`. Sin servidor muestra la muestra guardada.

## Qué se simula

En cada simulación se sortea, y se corre el gemelo completo (`Financials.step`) con el plan fijo de la R1:

| Incertidumbre | Cómo se sortea |
|---|---|
| Elasticidades de demanda (precio, marca, valor, cobertura) | Fila al azar de la **región factible** consistente con lo que vendió el 2.º lugar (38.003 / 316 / 18 combinaciones por producto) |
| Tamaño de mercado | Lognormal común (σ = 6 %) + ruido propio por producto (σ/2) |
| Conversión intención → venta | Con prob. 20 % vale ≈ 0,865 (observado en el Año 0); si no, 1,0 `[SUPUESTO]` |
| Ingresos extraordinarios R1 | 408.000 (prob. 70 %) o 138.000 `[SUPUESTO]` |

Dos modos de demanda: **Anclado** (por defecto: demanda del presupuesto × mercado × conversión, multiplicada por cómo reaccionan precio, marca, valor y cobertura a tus ajustes con elasticidades de la región factible; sin ajustes reproduce exactamente el presupuesto) y **Elasticidades** (solo el modelo).

Salida: resultado neto, ingresos, EBIT, efectivo, inventario, ROE, liquidez, proxy del valor de la compañía; percentiles P5/P25/P50/P75/P95, probabilidad de pérdida / de no llegar al presupuesto / de inventario alto / de caja baja / de crédito extraordinario, sensibilidad (correlación de rangos de Spearman) y convergencia de la media. Con la misma semilla el resultado es idéntico, sin importar el tamaño de lote.

Con **En vivo** activado, al cambiar un ajuste o un parámetro se vuelve a simular al instante.

## API

| Ruta | Descripción |
|---|---|
| `GET /` | App web |
| `GET /api/health` | `{"ok": true}` |
| `GET /api/plan` | Plan y corridas de referencia |
| `GET /api/simular?ajustes={"precio":[17.5,30.2,3.04],"nivel_capacidad":[2,1,0]}&modo=anclado&base=base&extra=408000` | Simulación determinista del plan ajustado + plan sin ajustes (P&G, balance, KPIs, productos) |
| `GET /api/real?ronda=1` | Resultados reales de la ronda (`data/real_r1.json`), ranking y comparación gemelo vs real |
| `GET /api/panel?ajustes={...}&modo=anclado&base=base&extra=408000` | Datos del panel por etapas: región factible de elasticidades y curvas demanda-precio (±15 %) con los ajustes actuales |
| `GET /api/montecarlo?n=5000&seed=42&modo=anclado&mkt_sigma=0.06&p_conv=0.2&p_extra_alto=0.7&ajustes={"precio":[18.4,30.2,3.04],"produccion":[235000,36000,32000]}` | Server-Sent Events: `inicio` → N × `lote` (estadísticas acumuladas) → `fin` |

Desde Python:

```python
from corbatul.montecarlo import MCConfig, correr
r = correr(MCConfig(n=5000, seed=1))
print(r["stats"]["neto"]["p5"], r["prob"]["perdida"])

from corbatul.simulador import simular
j = simular(ajustes={"precio": [17.5, 30.2, 3.04], "proyectos": ["proceso_productivo"]})
print(j["ajustado"]["kpi"]["neto"], j["plan"]["kpi"]["neto"])
```

Otras utilidades del gemelo: `python -m corbatul.twin backtest | replay | demand | pendientes | solve`.

## Nota sobre versiones del modelo

Este repositorio usa el gemelo **v2 calibrado** (carga de materia prima, almacenaje por tarifa, provisión de insolvencias = 1/3 de la variación de clientes, ROE de plataforma con ajuste de patrimonio). Con él, el plan R1 da **830.589** de resultado neto (base presupuesto, extraordinarios 408 k), frente a los 848.415 de la versión anterior usada en el Plan de Actuación y en las tarjetas «Proyección R1» de la app (−2,1 %).

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Publicar en GitHub

```bash
git init && git add . && git commit -m "Corbatul Twin: gemelo digital + Monte Carlo en tiempo real"
git branch -M main
git remote add origin https://github.com/<usuario>/corbatul-twin.git
git push -u origin main
```

GitHub Pages sirve solo contenido estático: `web/index.html` se verá con la muestra guardada; el modo en vivo necesita el servidor local (`python -m corbatul.server`). Safari bloquea conexiones `http://localhost` desde páginas `https://`; usa `./run.sh` (página y servidor en el mismo origen).

## Etiquetas del código

`[DATO]` leído del Excel o del simulador · `[INFERIDO]` deducido de cifras · `[SUPUESTO]` forma elegida por falta de datos · `[PENDIENTE]` por leer de la plataforma.


## Resultados reales

`data/real_rN.json` guarda el Cuadro de Mando de cada ronda. `python -m corbatul.real` imprime el ranking y el error del gemelo; `build/real_r1.py` los integra en el HTML.
