# Contexto para continuar en otro chat — Equipo OMEGA (RealMan) · ACBSP CompanyGame 2026 (CORBATUL)

Lee este archivo antes de tocar nada. Resume dónde quedamos al cierre de la R1 y el plan de la R2.

## Qué hay en este zip
| Ruta | Qué es |
|---|---|
| `web/index.html` | La app «Corbatul Twin» (mapa 3D, panel por etapas, tarjetas de Datos, Simulador y Monte Carlo). Es el HTML del usuario + parches de `build/conectar.py`, `build/real_r1.py`, `build/plan_r2.py` |
| `corbatul/twin.py` | Gemelo original (R1) |
| `corbatul/r2.py` | **Gemelo de la R2 calibrado con la R1 real** — de aquí sale el presupuesto R2. `python -m corbatul.r2` |
| `corbatul/real.py` | Resultados reales R1 vs gemelo. `python -m corbatul.real` |
| `corbatul/presupuesto.py` | Revisión del presupuesto R1 (desvíos y causas). `python -m corbatul.presupuesto` |
| `corbatul/server.py` | Servidor local (`python -m corbatul.server` → http://localhost:8765): `/api/simular`, `/api/montecarlo` (SSE), `/api/panel`, `/api/real` |
| `data/real_r1.json` | Todo el Cuadro de Mando R1: ranking, valor compañía, competencia, precios, marca, demanda (intención), márgenes, P&G |
| `data/balance_r1.json` | Balance de cierre R1, deuda, tipos, rating, activos fijos |
| `data/produccion_r1.json` | Costes de producción y logística R1 |
| `data/presupuesto_r1.json` | Presupuesto R1 enviado vs real |
| `data/proyectos_r2.json` | Las 4 tarjetas de proyectos de la R2 |
| `data/plan_r2.json` | **Plan y presupuesto R2 final** |
| `tests/` | `python -m unittest discover -s tests` (18 tests, todos pasan) |
| `build/` | Scripts que parchean el HTML (si el usuario manda otro HTML: `conectar.py` → `real_r1.py` → `plan_r2.py`; son idempotentes) |

## Resultado R1 (real)
- **RealMan 1.º de 7**, Valor de la Compañía 2.794 (+465; media 2.179). Mejor nota de Presupuestación (422 / 343).
- Ventas 301.872 u · ingresos 4.663.022 · margen 46,3 % · neto antes de impuestos 557.930 · impuesto 15.116 · neto 542.813.
- **Demanda (intención) muy por encima de la capacidad**: corbatas 366.000 vs 234.225 vendidas; bufandas 62.000 vs 35.739; calcetines 50.000 vs 31.908.
- Fuimos los más caros del sector (18,40 / 30,20 / 3,04) y aun así ganamos cuota (14,3 % → 17,6 %).

## Lecciones verificadas (reglas de la plataforma)
- Ventas = (producción + inventario inicial) / 1,0232 cuando la demanda supera a la oferta.
- Gastos generales = 146.472 × IPC (en R1 tuvimos +48.336 sin explicar; por eso en R2 cobro y pago a 45 días).
- Personal central 543.162 × (1 + IPC 2,7 %) + 3,5 % × ingresos (el incentivo SÍ se cobra, aunque el informe diga «volumen 0»).
- Dotación = Δclientes / 3. Clientes = ingresos T4 × DSO / 120.
- Almacenaje = 0,30 × suma de inventarios al cierre de los 4 trimestres. Transporte R2 = 0,21 / 0,17 / 0,13 por unidad.
- Impuesto 25 %: las pérdidas compensables se agotaron en R1.
- Extraordinario recurrente = 18.000 (el 408.000 del presupuesto R1 era un supuesto copiado; fue el 96 % del desvío).
- Activos financieros LP: la compra se SUMA al saldo existente (800 k + 150 k = 950 k).
- La línea «Resultado neto» del formulario de presupuesto es **antes de impuestos**.
- **Precio absoluto, sin tope de ±15 %** (rangos usados: 5–35 / 10–60 / 1–10).
- Tabla «Nivel de costes base de materia prima»: estándar y premium figuran a **0,00**. El ganador de la edición anterior (Excel ACBSP_2025.xlsx de «Landon»/SmartOne) eligió premium en su R2 y su materia prima salió en 0 (margen 65 %). **El equipo decidió elegir premium y presupuestar materia prima a 0.** Riesgo: si la cobran a precio premium (3,50 / 7,50 / 0,80) el neto cae ~960.000.

## Plan R2 decidido (data/plan_r2.json)
| | Corbatas | Bufandas | Calcetines |
|---|---|---|---|
| Precio | 20,25 | 31,50 | 3,50 |
| Ampliación / capacidad | Nivel 2 → 275.000 (320 k) | Nivel 2 → 55.000 (220 k) | — 40.000 |
| Producción | 100 % | 100 % | 100 % |
| Materia prima | Premium (coste 0) | Premium | Premium |
| Promoción | 170.000 | 150.000 | 50.000 |
| Gama | 23 | 11 | 5 |

Proyectos: digitalización (125 k), automatización almacén (125 k), layout (0), patronaje bufandas (0). Descuento 15 %, incentivo 3,5 %, mantenimiento 4 %, cobro y pago 45 días. Sin préstamo nuevo ni compra de activos financieros. Inversión 790.000; caja T1 ≈ 450.000.

**Presupuesto R2**: ingresos 6.297.157 · coste fabricación 2.052.712 · margen 4.104.417 (65 %) · resultado bruto 2.176.643 · **resultado neto (formulario, antes de impuestos) 2.196.491** · impuesto 549.123 · neto después de impuestos 1.647.368 · activo total 7.585.941 · efectivo 2.321.349.
Monte Carlo: desvío medio del neto vs presupuesto 1,3 %. Precios elegidos para que la demanda supere la capacidad con ≥ 85 % de probabilidad (presupuesto exacto).

## Pendiente / próximos pasos
1. Confirmar en la pantalla de decisión de la R2 que premium sigue a 0,00 antes de enviar.
2. Tras la R2: cargar el Cuadro de Mando real, comparar con `data/plan_r2.json` y recalibrar `corbatul/r2.py` para la R3 (el ganador planificó R3 con 295.000 / 46.000 / 40.000 de capacidad y precios 22,90 / 30,90 / 4,30).
3. Preferencias del usuario: respuestas en español; HTML estilo iOS (bento, radio 28 px, solo colores existentes); en «Datos» solo tablas; gráficas en el panel del mapa por etapa.
