# -*- coding: utf-8 -*-
"""
CORBATUL · Gemelo Digital (Shadow Simulator) + Optimizador  ·  v2 (calibrado)
8vo Torneo ACBSP-CompanyGame · Categoría Finanzas/Contaduría

QUÉ CAMBIÓ RESPECTO A v1 (esqueleto con placeholders)
  * Año 0 REAL inyectado (balance, P&G, costes, capacidad, precios). Fuente: Excel del 2º lugar
    (columna "2024" = Año 0) y capturas del simulador (RealMan; los números del Año 0 son idénticos).
  * Mecánica de COSTES verificada contra el Año 0 (ver backtest_year0): CUF = MP + elaboración + energía
    + personal + (depreciación + generales de fábrica)/unidades. Tablas de ocupación, gama y diseño reales.
  * Mecánica de GASTOS/BALANCE descubierta a partir de los datos (incentivo 3,5% s/ingresos, clientes =
    ingresos Q4 x días/120, impuesto 25% con pérdidas acumuladas, depreciación 10%, etc.).
  * DEMANDA: no se inventa un valor puntual. Se calcula la REGIÓN FACTIBLE de elasticidades que es
    consistente con lo que vendió el 2º lugar (observaciones exactas + cotas inferiores) y el optimizador
    es ROBUSTO sobre esa región. La Ronda 1 del torneo sirve para estrechar la región (DemandCalibrator).
  * Marca: modelo ajustado (error ~2 puntos) con 12 transiciones del Excel.
  * Proyectos de inversión por ronda (R1 inferido de cifras; R2/R3 con el texto explícito del Excel).

CONVENCIÓN DE ETIQUETAS (búscalas con Ctrl+F)
  [DATO]       cifra leída tal cual del Excel/capturas.
  [INFERIDO]   deducido de cifras (se explica cómo); confirmar en la plataforma.
  [SUPUESTO]   forma funcional elegida por falta de datos; baja confianza.
  [PENDIENTE]  dato que el equipo debe leer del Cuadro de Mando en la Ronda 1.

USO RÁPIDO
  python twin.py backtest      # reproduce el Año 0 y valida la mecánica de costes
  python twin.py replay        # reproduce la Ronda 1 del 2º lugar con sus decisiones reales y compara
  python twin.py pendientes    # lista de datos a leer de la plataforma
  python twin.py demand        # región factible de elasticidades
  python twin.py solve         # optimiza el plan (rápido, horizonte 2)
  python twin.py solve 4       # plan completo de 4 rondas (más lento)
"""
from __future__ import annotations
import copy
import sys
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import minimize

PRODUCTS = ("corbatas", "bufandas", "calcetines")
QUALITIES = ("economica", "estandar", "premium")
P = 3

# ======================================================================
# 0. REGLAS Y TABLAS DEL SIMULADOR
# ======================================================================
RULES = dict(
    extra_credit_coef=0.50,     # [DATO cap.73] coef. de variación crédito extraordinario sobre referencia
    lp_coef=0.30,               # [DATO cap.73]
    cp_coef=0.15,               # [DATO cap.73]
    rating_adj_pts=((0.0, 0.50), (59.8, 0.204), (100.0, -0.12)),  # [INFERIDO] +50%..-12% (cap.73); ancla 59,8 -> +20,4%
    fa_cp_factor=0.90,          # [DATO Excel Balances] rinde ref x 0,9  (5.063/125.000 = 4,05% = 4,5% x 0,9)
    fa_lp_factor=1.25,          # [DATO] 8.445/150.000 = 5,63% = 4,5% x 1,25
    lp_years=8,                 # [DATO cap.74] vigencia LP 8 años, cuotas trimestrales (francés)
    tax_rate=0.25,              # [INFERIDO] 505.143/2.020.574 = 25,0% en 2026 del 2º lugar
    sales_incentive_base=0.035, # [DATO] 117.136/3.346.747
    provision_share=1.0 / 3.0,  # [DATO x2] dotación por insolvencias = (clientes_fin - clientes_ini) / 3
    dep_rate=0.10,              # [DATO cap.80] fábrica/central/almacén 10%; edificios e inmaterial 4%
    dep_first_year=0.75,        # [INFERIDO] 2025 del 2º lugar: 234.750 = 180.000 + 10% x 730.000 x 0,75 (inconsistente en 2026)
    q4_share=0.25,              # [DATO] participación trimestral ~25% (Ventas!W19:Z19)
    cli_days_div=120.0,         # [INFERIDO] clientes = ingresos_Q4 x días/120  (327.035 = 872.093 x 45/120 exacto)
    h1_share=0.5,               # [INFERIDO] obsolescencia: lo no vendido al cierre del 2º trimestre -> ~50% de la demanda anual
    gama_max=(25, 15, 10),      # [DATO manual §2.6]
    vol_discounts=(0.0, 0.07, 0.15),   # [DATO manual §2.8] (el PDF trae % cruzados en nivel 2/3; se asume orden creciente)
    gama_idx_eff_min=0.70,      # [SUPUESTO] piso del factor anual de eficiencia por mantenimiento
)
# Pesos del Valor de la Compañía (manual §7). Presupuestación (33%) se controla con calibración.
WEIGHTS = dict(econ=0.34, solv=0.10, brand=0.09, product=0.09, share=0.05)

# [DATO Producción 2025] MP total = unidades producidas x precio de lista x carga: 344.760/(195.000x1,70)=1,040; 117.959/(25.000x4,60)=1,0257; 13.453/(28.000x0,45)=1,0677
# (2024: 1,04/1,02/1,01). Origen no documentado -> se usa la carga 2025. El replay del 2º lugar mejora con ella (coste fabricación -1,3% -> ~0%).
MP_LOAD = (1.040, 1.0257, 1.0677)

def storage_cost(avg_units_total):
    """[INFERIDO] Almacenaje PT = tarifa x 4 x unidades medias en inventario (suma de productos). Tarifa observada plana por año:
    0,30 (2025, inv. medio 6.068 u) y 0,45 (2024, 9.859 u); sobre 9.859 sigue la pendiente de la tabla (0,08 por 7.500 u).
    Reproduce 7.282 vs 7.334 real en 2025."""
    rate = float(np.interp(avg_units_total, [0.0, 6112.0, 9859.0, 60000.0], [0.28, 0.30, 0.45, 0.45 + (60000.0 - 9859.0) * 0.08 / 7500.0]))
    return rate * 4.0 * avg_units_total

# [DATO Balance] el "Patrimonio Neto" que usa la plataforma en sus ratios = patrimonio contable + 246.390 (3.979.739 vs 3.733.349; igual en 2024).
# ROE plataforma 2025: -105.110 / 3.979.739 = -2,64% (mostrado -2,6%). Origen de los 246.390 desconocido: se supone constante.
EQ_OFFSET = 246_390.0

# [DATO Activo fijo 2025] valor neto contable y depreciación anual por activo existente; la depreciación se detiene al llegar a 0
NBV0 = dict(fab=450_000.0, alm=33_750.0, cen=192_500.0, bld=399_500.0, imm=164_500.0)
DEP_AMT = dict(fab=180_000.0, alm=22_500.0, cen=55_000.0, bld=34_000.0, imm=14_000.0)

# --- Índices de coste de elaboración [DATO Excel Producción filas 84-96, idénticos para los 3 productos en ocupación]
OCC_X = (0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0)
OCC_Y = (0.54, 0.54, 0.429, 0.284, 0.18, 0.078, 0.045)       # factor = 1 + Y(ocupación)  [verificado: 1,076 a 90,7%]
GAMA_X = (1, 3, 5, 7, 9, 11, 13, 16, 19, 21, 23, 25)
GAMA_Y = (  # factor multiplicativo por producto
    (1.00, 1.01, 1.02, 1.04, 1.06, 1.09, 1.12, 1.15, 1.18, 1.19, 1.21, 1.23),   # corbatas
    (1.00, 1.05, 1.07, 1.10, 1.13, 1.15, 1.19, 1.22, 1.22, 1.22, 1.22, 1.22),   # bufandas
    (1.00, 1.05, 1.08, 1.12, 1.15, 1.16, 1.16, 1.16, 1.16, 1.16, 1.16, 1.16),   # calcetines
)
DESIGN_X = (1, 3, 5, 7, 8, 10)
DESIGN_Y = (1.00, 1.02, 1.06, 1.10, 1.13, 1.16)              # nivel 1 extrapolado a 1,00 [SUPUESTO]
# --- Coste de almacenaje unitario según volumen almacenado [DATO Logística B33:C43] (efecto menor)
# --- Ampliación de capacidad (unidades extra, inversión) niveles 0..3 [DATO Producción D164:F170]
EXPANSION = (
    ((0, 0), (20000, 140000), (40000, 320000), (60000, 750000)),   # corbatas
    ((0, 0), (8000, 120000), (17000, 220000), (45000, 450000)),    # bufandas
    ((0, 0), (35000, 130000), (50000, 170000), (125000, 450000)),  # calcetines
)
RAW_COST = ((1.7, 2.4, 3.5), (4.6, 6.7, 7.5), (0.45, 0.60, 0.80))   # [DATO Producción C72:E74] económica/estándar/premium
RAW_TIERS = ((150000, 200000), (25000, 60000), (30000, 70000))      # [DATO manual §2.8]

# --- Proyectos de inversión por ronda (r = 1..4) ---------------------------------------------------------
# effects: multiplicadores permanentes. asset: 'fab' (AF fábrica, su depreciación entra en coste de producto),
#          'otro' (AF no fabril, depreciación en gastos operación) o 'gasto' (va a gastos generales).
PROJECTS = {
    # --- R1: tarjetas de la plataforma (Decisiones > Otros proyectos). known=False => importe/efecto NO visible: el optimizador NO lo adopta
    "proceso_productivo":     dict(r=1, cost=(250000, 70000, 25000), asset="fab",  eff=dict(elab=0.75, pers=0.90), known=True,
                                   note="[DATO] hasta -25% elaboración; inversión 250k/70k/25k; SOLO las 3 primeras solicitudes. Personal -10% [INFERIDO 2º lugar]"),
    "eficiencia_energetica": dict(r=1, cost=(125000, 0, 0),          asset="fab",  eff=dict(energy=0.724), known=True,
                                   note="[DATO] hasta -30% energía; 125.000; SOLO las 3 primeras solicitudes. 0,724 = lo realizado por el 2º lugar (conservador)"),
    "nuevos_proveedores":    dict(r=1, cost=(225000, 0, 0),          asset="otro", eff=dict(mp=0.79, mp_calc=0.76), known=False,
                                   note="[INFERIDO 2º lugar] importe y % de reducción NO visibles en tu tarjeta -> no se adopta hasta confirmarlos"),
    "calidad_producto":      dict(r=1, cost=(0, 0, 0),               asset="otro", eff=dict(), known=False,
                                   note="[PENDIENTE] inversión por producto no visible"),
    "condiciones_laborales": dict(r=1, cost=(0, 0, 0),               asset="gasto", eff=dict(pers=1/1.18), known=False,
                                   note="[DATO parcial] +18% productividad; importe no visible. Efecto modelado como personal/1,18 (supuesto)"),
    "codigo_conducta":       dict(r=1, cost=(0, 0, 0),               asset="gasto", eff=dict(), known=False, note="[PENDIENTE] gastos generales; importe no visible"),
    "esg_r1":                dict(r=1, cost=(0, 0, 0),               asset="gasto", eff=dict(), known=False, note="[PENDIENTE] importe no visible"),
    "reparacion_edificio":   dict(r=1, cost=(0, 0, 0),               asset="gasto", eff=dict(), known=False, note="[PENDIENTE] 3 opciones; la 3 es gasto de P&L; importes no visibles"),
    "venta_terreno":         dict(r=1, cost=(0, 0, 0),               asset="gasto", eff=dict(), known=False,
                                   note="[DATO] oferta 265.000 vs contable 375.000 (pérdida 110.000, la tarjeta dice 50.000: incoherente); pierde 18.000/año de ingreso extraordinario; decisión única del equipo"),
    "ampliacion_capital_vc": dict(r=1, cost=(0, 0, 0),               asset="gasto", eff=dict(), known=False, note="[PENDIENTE] importe del aumento de capital (2 pagos anuales) no visible"),
    # --- R2: texto explícito en Excel 'Inversiones' [DATO]
    "automatizacion_almacen": dict(r=2, cost=(125000, 0, 0),         asset="otro", eff=dict(demand=1.08),
                                   note="[DATO] +8% ventas ya en el primer año"),
    "digitalizacion_diseno":  dict(r=2, cost=(125000, 0, 0),         asset="otro", eff=dict(pers=0.92, design_plus=1.0),
                                   note="[DATO] -8% personal de producción y +1 nivel de diseño en todos los productos"),
    "layout_planta":          dict(r=2, cost=(65000, 0, 0),          asset="gasto", eff=dict(gen_fab=0.92, elab=0.92),
                                   note="[DATO] -8% generales de fábrica y -8% elaboración (se contabiliza como gasto general)"),
    "patronaje_bufandas":     dict(r=2, cost=(0, 85000, 0),          asset="otro", eff=dict(mp_buf=0.88),
                                   note="[DATO] -12% MP bufandas"),
    # --- R3
    "fiabilidad_produccion":  dict(r=3, cost=(60000, 35000, 18000),  asset="fab",  eff=dict(defect=0.75, merma=0.75),
                                   note="[DATO] -25% unidades defectuosas y % de merma"),
    "ia_planificacion":       dict(r=3, cost=(75000, 0, 0),          asset="otro", eff=dict(mp=0.91, storage=0.91),
                                   note="[DATO] -9% MP y -9% almacenaje"),
    "esg":                    dict(r=3, cost=(85000, 0, 0),          asset="otro", eff=dict(),
                                   note="[DATO] 'mejor reputación' sin efecto cuantificado -> efecto 0 (solo coste)"),
}


USE_VOLUME_TIERS = False   # [INFERIDO] R1 del 2º lugar: MP real = tabla x proyecto x IPC, sin escalón de volumen visible


def _interp(x, xs, ys): return float(np.interp(x, xs, ys))

MKT0 = (1_367_310.0, 175_322.0, 195_881.0)   # [DATO Excel Mercado] unidades totales de las 7 compañías en el Año 0


# ======================================================================
# 1. DATOS DEL AÑO 0 Y DEL ENTORNO
# ======================================================================
@dataclass
class ProductData:
    name: str
    price0: float; demand0: float; brand0: float; value0: float; design0: float; gama0: float; cap0: float
    inv_units0: float; inv_value0: float
    elab_base: float; energy_unit: float; pers_pool: float; transport: float; storage: float
    defect: float; merma: float
    promo_base: float; design_hold: float; design_climb: float
    units_sold0: float
    design_free: float = 0.0     # niveles de diseño que se suben sin coste adicional sobre el presupuesto base


def year0_products():
    """[DATO] Año 0 = columna 2024 del Excel del 2º lugar. demand0 = intención de compra total mercado (1.580k/206k/232k, captura usuario) / 7 compañías."""
    return [
        ProductData("corbatas", 16.20, 225714, 37, 8.0, 4, 15, 215000, 4666, 34248, 1.29, 0.41, 684450, 0.19, 0.030,
                    0.0900, 0.38, 75000, 48000, 36001, 195330),
        ProductData("bufandas", 27.90, 29429, 31, 6.3, 3, 6, 30000, 573, 7638, 2.11, 0.56, 136250, 0.16, 0.026,
                    0.0905, 0.46, 65000, 32000, 42667, 25046),
        ProductData("calcetines", 2.65, 33143, 25, 7.1, 3, 5, 40000, 649, 980, 0.19, 0.12, 18200, 0.13, 0.028,
                    0.0942, 0.62, 45000, 64000, 36000, 27983, 1.0),  # calcetines: 64.000 cubrió N3->N4 [DATO]; niveles >N4 [SUPUESTO 36.000]; demand0 [PENDIENTE exacto]
    ]


@dataclass
class Company:
    """Parámetros de empresa (no por producto)."""
    af_fab: float = 1_800_000        # [DATO cap.80] activo fijo de fábrica
    gen_fab: float = 156_750         # [DATO Producción B154] generales de fábrica
    dep_other: float = 125_500       # [DATO] edificios 34.000 + central 55.000 + almacén 22.500 + inmaterial 14.000
    central_pers: float = 525_810    # [DATO Resultados C131] personal de estructura (crece con IPC)
    general_adm: float = 141_793     # [DATO] procesos administrativos (crece con IPC)
    maint_year0: float = 46_800      # [DATO] mantenimiento Año 0 = 2,6% del AF fábrica
    maint_pct0: float = 0.026
    participations: float = 305_000  # [DATO cap.83]
    rm_inventory: float = 35_316     # [DATO] inventario materia prima (balance 78.183 = PT 42.866 + MP 35.316) [SUPUESTO: constante]
    existing_debt: float = 1_502_874 # [DATO] LP 1.219.666 + parte CP 283.208
    existing_sched: tuple = (274_275, 291_461, 321_959, 330_000)  # [INFERIDO] amortización real del 2º lugar: Δ deuda total R1..R3 (Balances A78:E78); R4 supuesto
    existing_rate: float = 0.0408    # [INFERIDO] 55.673 / saldo medio 2025 del 2º lugar
    nol0: float = 497_464            # [INFERIDO] 25% x (999.768 - 502.304): el 2º lugar pagó 125.576 de impuesto en R1
    rating0: float = 59.8            # [DATO cap.73]
    eff_a: float = 0.30              # [SUPUESTO] efecto máximo anual de mantenimiento sobre elaboración
    eff_b: float = 0.5446            # calibrado: delta(4,0% de AF fábrica)=0,84  (observado 0,82-0,86 en 3 años)
    eff_m0: float = 0.026            # [DATO] mantenimiento base sin mejora
    dpo_safe: float = 45.0           # [DATO captura Financiación] plazo Año 0 = 45 días (cobro también 45)
    dpo_pen: float = 0.05            # [SUPUESTO] sobreprecio MP por cada 30 días sobre dpo_safe
    pay_k: float = 0.458             # [INFERIDO] proveedores = MP x pay_k x DPO/45. R1 2º lugar: 249.224/489.797=0,51 (Año 0 fue 0,443) -> recalibrar con BudgetCalibrator
    cover0: float = 0.572            # [DATO Indicadores] cobertura de distribución
    disc0: float = 0.15              # [DATO]
    cover_gain: float = 1.0          # [SUPUESTO] d(cobertura)/d(descuento canal); el 2º lugar nunca lo movió de 15%
    cover_drift: float = 0.045       # [INFERIDO] deriva anual observada .572->.637->.709->.746->.783 con descuento constante
    brand_g: float = 14.0            # [INFERIDO] ajuste de marca (rmse 2,0 pts, 12 transiciones)
    brand_c: float = 4.6
    k_value_design: float = 0.42     # [INFERIDO] MCO sobre 4 transiciones 2º lugar: dValor = 0,42 x dDiseño + 0,27 x dGama (R2 baja; producto-dependiente)
    k_value_gama: float = 0.27       # [INFERIDO] valor de producto por unidad de amplitud de gama
    k_value_quality: float = 0.5     # [SUPUESTO]
    extraordinary: tuple = (0.0, 0.0, 0.0, 0.0)  # [PENDIENTE] el 2º lugar tuvo 408.000 en R1 y R2 (origen no explicado)


@dataclass
class Macro:
    """Escenario por ronda R1..R4 (2026..2029). R1 verificado (ref 4,9% en rendimiento de AF del 2º lugar); R2-R4 [SUPUESTO] de la tabla macro. 2025 real: IPC 3,1%, ref 4,5%."""
    ipc: tuple = (0.033, 0.027, 0.037, 0.030)
    ref: tuple = (0.049, 0.033, 0.052, 0.045)
    conv: float = 1.0      # conversión intención->ventas (Año 0: 195.330/225.714 = 0,865). 1,0 = la diferencia era solo falta de stock; 0,865 = se repite aunque haya stock
    # índice de tamaño de mercado vs Año 0 por producto y ronda (unidades totales de las 7 compañías) [DATO Excel Mercado]
    mkt_idx: tuple = (
        (1.0251, 0.9291, 0.9173, 1.0498),     # corbatas
        (1.0132, 1.0130, 0.9421, 1.0364),     # bufandas
        (1.0362, 1.0976, 0.9520, 1.2097),     # calcetines
    )


def macro_variants():
    base = Macro()
    pess = Macro(mkt_idx=tuple(tuple(v * 0.90 for v in row) for row in base.mkt_idx))
    opt = Macro(mkt_idx=tuple(tuple(v * 1.05 for v in row) for row in base.mkt_idx))
    conv = Macro(conv=0.865)
    return [("base", base, 0.4), ("pesimista", pess, 0.25), ("optimista", opt, 0.15), ("conv86", conv, 0.20)]


# ======================================================================
# 2. DEMANDA: región factible (no valor puntual) + dinámica de marca/valor
# ======================================================================
# Observaciones del 2º lugar (índices 2023..2028).  exact=True -> quedó inventario, la venta = demanda.
_OBS = dict(
    mk=dict(corb=[1361528, 1367310, 1401548, 1270331, 1254197, 1435276], buf=[177317, 175322, 177644, 177603, 165171, 181698],
            calc=[193956, 195881, 202978, 215002, 186490, 236968]),
    cov=[.506, .572, .637, .709, .746, .783],
    price=dict(corb=[16.0, 16.2, 18.4, 19.9, 22.9, 19.9], buf=[26.6, 27.9, 30.2, 30.4, 30.9, 30.9], calc=[2.4, 2.65, 3.05, 4.3, 4.3, 4.0]),
    brand=dict(corb=[35, 37, 44, 56, 67, 74], buf=[28, 31, 38, 52, 62, 77], calc=[22, 25, 32, 39, 47, 62]),
    value=dict(corb=[8, 8, 9.6, 10, 10, 10], buf=[6.3, 6.3, 8.4, 10, 10, 10], calc=[7.1, 7.1, 7.5, 8.1, 10, 10]),
    sold=dict(corb=[194504, 195330, 234222, 254542, 238229, 352805], buf=[25331, 25046, 33981, 37912, 45815, 40252],
              calc=[27708, 27983, 28001, 28000, 34892, 33412]),
    exact=dict(corb=[0, 0, 0, 0, 1, 0], buf=[0, 0, 0, 0, 0, 1], calc=[0, 0, 0, 0, 1, 1]),
)
_KEYS = ("corb", "buf", "calc")


def feasible_demand_params(i: int, n_try=300_000, seed=7, tol_exact=0.20, tol_lower=0.10):
    """Elasticidades (e_price, e_brand, e_value, e_cover) consistentes con las observaciones del 2º lugar.
    Devuelve array (m,4). Pocas muestras = región casi vacía = el modelo log-lineal explica mal ese producto."""
    k = _KEYS[i]; rng = np.random.default_rng(seed + i)
    ep = -rng.uniform(0.3, 6.0, n_try); eb = rng.uniform(0, 2, n_try); ev = rng.uniform(0, 3, n_try); ec = rng.uniform(0, 3, n_try)
    ok = np.ones(n_try, bool); d0 = year0_products()[i].demand0; t0 = 1
    for t in range(6):
        if t == t0: continue
        pred = (d0 * (_OBS["price"][k][t] / _OBS["price"][k][t0]) ** ep * (_OBS["brand"][k][t] / _OBS["brand"][k][t0]) ** eb
                * (_OBS["value"][k][t] / _OBS["value"][k][t0]) ** ev * (_OBS["cov"][t] / _OBS["cov"][t0]) ** ec
                * (_OBS["mk"][k][t] / _OBS["mk"][k][t0]))
        s = _OBS["sold"][k][t]
        ok &= (np.abs(np.log(pred / s)) <= tol_exact) if _OBS["exact"][k][t] else (pred >= (1 - tol_lower) * s)
    return np.column_stack([ep, eb, ev, ec])[ok]


def demand_scenarios(n_levels=3):
    """Convierte la región factible en `n_levels` conjuntos de elasticidades (percentiles 20/50/80 de |e_price|) por producto."""
    out = []
    for q in np.linspace(20, 80, n_levels):
        row = []
        for i in range(P):
            S = feasible_demand_params(i)
            if len(S) < 5:        # región casi vacía: usar el mejor ajuste "blando"
                S = feasible_demand_params(i, tol_exact=0.35, tol_lower=0.25)
            if len(S) == 0:
                row.append(np.array([-1.5, 0.3, 0.5, 0.5]))
            else:
                j = np.argsort(S[:, 0]); row.append(S[j[int(q / 100 * (len(S) - 1))]])
        out.append(np.array(row))
    return out        # lista de arrays (3 productos x 4 elasticidades)


class MarketDemand:
    def __init__(self, prods, comp: Company): self.pp, self.cp = prods, comp

    def demand(self, i, price, brand, value, cover, el, mkt_idx, mult=1.0):
        p = self.pp[i]; e = el[i]
        d = (p.demand0 * (price / p.price0) ** e[0] * (brand / p.brand0) ** e[1] * (value / p.value0) ** e[2]
             * (cover / self.cp.cover0) ** e[3] * mkt_idx * mult)
        return max(float(d), 0.0)

    def brand_next(self, i, brand, promo):
        c, p = self.cp, self.pp[i]
        nb = brand + c.brand_g * np.log(max(promo, 1.0) / p.promo_base) * (100 - brand) / 100 + c.brand_c
        return float(np.clip(nb, 10, 100))

    def value_next(self, i, value, d_design, d_gama, d_quality):
        c = self.cp
        return float(np.clip(value + c.k_value_design * d_design + c.k_value_gama * d_gama + c.k_value_quality * d_quality, 1, 10))

    def cover_next(self, cover, disc):
        return float(np.clip(cover + self.cp.cover_drift + self.cp.cover_gain * (disc - self.cp.disc0), 0.2, 0.95))


# ======================================================================
# 3. COSTES DE PRODUCCIÓN (verificado contra Año 0)
# ======================================================================
class ProductionCosts:
    def __init__(self, prods, comp): self.pp, self.cp = prods, comp

    @staticmethod
    def f_occ(o): return 1.0 + _interp(o, OCC_X, OCC_Y)
    @staticmethod
    def f_gama(i, g): return _interp(g, GAMA_X, GAMA_Y[i])
    @staticmethod
    def f_design(d): return _interp(d, DESIGN_X, DESIGN_Y)

    def eff_factor(self, maint_pct):
        """Factor ANUAL multiplicativo sobre el índice de eficiencia (stock). 1,0 con mantenimiento base; <1 mejora."""
        c = self.cp; x = max(maint_pct - c.eff_m0, 0.0) * 100.0
        if maint_pct < c.eff_m0: return 1.0 + 4.0 * (c.eff_m0 - maint_pct)            # [SUPUESTO] erosión si se recorta
        return max(1.0 - c.eff_a * (1.0 - np.exp(-c.eff_b * x)), RULES["gama_idx_eff_min"])

    # volumen de compra del Año 0 (unidades producidas); los costes de RAW_COST ya vienen NETOS de descuento a ese volumen
    VOL0 = (195000.0, 25000.0, 28000.0)

    @staticmethod
    def _disc(i, v):
        """Descuento por volumen (manual §2.8), con escalón suavizado (+-1% del umbral) para no romper al optimizador."""
        t1, t2 = RAW_TIERS[i]; d = RULES["vol_discounts"]
        sg = lambda x: 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))
        return d[0] + (d[1] - d[0]) * sg((v - t1) / (0.01 * t1)) + (d[2] - d[1]) * sg((v - t2) / (0.01 * t2))

    def raw_unit(self, i, q, volume, dpo, mp_mult):
        """[INFERIDO] En el Año 0 (195k corbatas > 150k) el coste observado es 1,70 = precio de tabla sin descuento visible,
        por lo que RAW_COST se trata como coste efectivo al volumen Año 0 y solo se ajusta por CAMBIO de tramo.
        [PENDIENTE] leer en la plataforma la tabla de MP por proveedor de cada ronda (ya trae el descuento)."""
        rel = ((1 - self._disc(i, volume)) / (1 - self._disc(i, self.VOL0[i]))) if USE_VOLUME_TIERS else 1.0
        over = max(dpo - self.cp.dpo_safe, 0.0) / 30.0
        return RAW_COST[i][int(q)] * rel * mp_mult * (1 + self.cp.dpo_pen * over)

    def unit_components(self, i, units, capacity, gama, design, q, dpo, S, share_cap):
        """Descompone el coste unitario de fabricación. S = estado con multiplicadores y pools."""
        occ = min(units / max(capacity, 1.0), 1.0)
        elab = (S["elab_base"][i] * self.f_occ(occ) * self.f_gama(i, gama) * self.f_design(design) * S["eff"] * S["m"]["elab"])
        mp = self.raw_unit(i, q, units, dpo, S["m"]["mp"] * S["m"]["mp_infl"] * (S["m"]["mp_buf"] if i == 1 else 1.0) * (S["m"]["mp_calc"] if i == 2 else 1.0)) * MP_LOAD[i]
        energy = S["energy"][i] * S["m"]["energy"]
        pers = S["pers_unit"][i] * S["m"]["pers"]       # [INFERIDO] R1 2º lugar: 3,51->3,26 / 5,45->5,07 / 0,65->0,61 = x1,033 x0,90 en los 3 productos
        dep = share_cap * S["dep_fab"] / max(units, 1.0)
        gen = share_cap * S["gen_fab_now"] / max(units, 1.0)
        return dict(mp=mp, elab=elab, energy=energy, pers=pers, dep=dep, gen=gen, occ=occ)


# ======================================================================
# 4. ESTADO, DECISIONES Y FINANCIEROS
# ======================================================================
@dataclass
class State:
    cash: float; clients: float; payables: float
    inv_units: np.ndarray; inv_cost: np.ndarray; rm_inv: float
    debt_old: float; tranches: list          # tranches: [(saldo, tipo)]  préstamos nuevos LP (francés 8 años)
    debt_cp: float; fa_cp: float; fa_lp: float
    af_gross: float; acc_dep: float; equity: float
    brand: np.ndarray; value: np.ndarray; design: np.ndarray; gama: np.ndarray; capacity: np.ndarray
    cover: float; eff: float; nol: float
    elab_base: np.ndarray; energy: np.ndarray; pers_pool: np.ndarray
    central: float; general: float; af_fab: float; gen_fab: float; dep_other: float
    mult: dict; adopted: set; t: int = 0
    last_units: np.ndarray = None
    tax_payable: float = 0.0
    price: np.ndarray = None
    nbv: dict = None


def initial_state(prods, comp: Company) -> State:
    one = np.ones(P)
    inv_cost = np.array([p.inv_value0 / p.inv_units0 for p in prods])
    st = State(cash=1_916_796, clients=327_035, payables=211_042,
               inv_units=np.array([p.inv_units0 for p in prods], float), inv_cost=inv_cost, rm_inv=comp.rm_inventory,
               debt_old=comp.existing_debt, tranches=[], debt_cp=0.0, fa_cp=125_000, fa_lp=150_000,
               af_gross=5_080_000, acc_dep=2_534_750, equity=0.0,
               brand=np.array([p.brand0 for p in prods], float), value=np.array([p.value0 for p in prods], float),
               design=np.array([p.design0 for p in prods], float), gama=np.array([p.gama0 for p in prods], float),
               capacity=np.array([p.cap0 for p in prods], float), cover=comp.cover0, eff=1.0, nol=comp.nol0,
               elab_base=np.array([p.elab_base for p in prods]), energy=np.array([p.energy_unit for p in prods]),
               pers_pool=np.array([p.pers_pool / u for p, u in zip(prods, (195000.0, 25000.0, 28000.0))]), central=comp.central_pers, general=comp.general_adm,
               af_fab=comp.af_fab, gen_fab=comp.gen_fab, dep_other=comp.dep_other,
               mult=dict(elab=1.0, energy=1.0, pers=1.0, mp=1.0, mp_infl=1.0, mp_buf=1.0, mp_calc=1.0, gen_fab=1.0, defect=1.0, merma=1.0,
                         storage=1.0, demand=1.0),
               adopted=set(), last_units=np.array([195000.0, 25000.0, 28000.0]), price=np.array([p.price0 for p in prods]))
    assets = (st.af_gross - st.acc_dep) + comp.participations + st.fa_lp + st.fa_cp + st.inv_value + st.clients + st.cash
    st.nbv = dict(NBV0)
    st.equity = assets - st.debt_old - st.payables           # 3.733.349  [DATO: capital + reservas + resultado]
    return st


State.inv_value = property(lambda s: float(np.sum(s.inv_units * s.inv_cost)) + s.rm_inv)


@dataclass
class Decisions:
    occ: np.ndarray; promo: np.ndarray; gama: np.ndarray; design_up: np.ndarray
    maint_pct: float; channel_discount: float; sales_incentive: float; dso: float; dpo: float
    new_lp: float; new_cp: float; fa_cp: float; fa_lp: float; dividend_pct: float
    price: np.ndarray = None       # precio absoluto (alternativa a dprice)
    dprice: np.ndarray = None      # variación relativa de precio vs periodo previo, |d|<=15% [DATO captura Ventas]
    quality: np.ndarray = field(default_factory=lambda: np.zeros(P))
    cap_level: np.ndarray = field(default_factory=lambda: np.zeros(P))
    projects: tuple = ()


def loan_rate(kind, ref, rating):
    coef = {"lp": RULES["lp_coef"], "cp": RULES["cp_coef"], "extra": RULES["extra_credit_coef"]}[kind]
    adj = _interp(rating, [a for a, _ in RULES["rating_adj_pts"]], [b for _, b in RULES["rating_adj_pts"]])
    return ref * (1 + coef) * (1 + adj)


def french_split(balance, rate, years_left):
    """Cuota anual constante: devuelve (interés, principal) del año para un préstamo con `years_left` años restantes."""
    if years_left <= 0 or balance <= 0: return balance * rate, balance
    a = balance * rate / (1 - (1 + rate) ** -years_left) if rate > 0 else balance / years_left
    return balance * rate, min(a - balance * rate, balance)


class Financials:
    def __init__(self, prods, comp, demand: MarketDemand, costs: ProductionCosts):
        self.pp, self.cp, self.dm, self.pc = prods, comp, demand, costs

    def step(self, st: State, d: Decisions, mac: Macro, el, r: int, dem_override=None):
        """Simula la ronda r (1..4). Devuelve (nuevo_estado, informe)."""
        pp, cp, R = self.pp, self.cp, RULES
        new = copy.deepcopy(st); new.t = st.t + 1; k = r - 1
        price = np.array(d.price, float) if d.dprice is None else st.price * (1 + np.clip(d.dprice, -0.15, 0.15))
        new.price = price
        ipc, ref = mac.ipc[k], mac.ref[k]

        # ---- proyectos adoptados esta ronda -------------------------------------------------------
        capex_fab = capex_otro = gasto_proj = 0.0
        for name in d.projects:
            pj = PROJECTS[name]
            if name in new.adopted or pj["r"] != r: continue
            new.adopted.add(name); tot = float(sum(pj["cost"]))
            if pj["asset"] == "fab": capex_fab += tot
            elif pj["asset"] == "otro": capex_otro += tot
            else: gasto_proj += tot
            for key, v in pj["eff"].items():
                if key == "design_plus": new.design = np.minimum(new.design + v, 10)
                else: new.mult[key] *= v
        # ---- ampliación de capacidad -------------------------------------------------------------
        cap_add = np.array([EXPANSION[i][int(d.cap_level[i])][0] for i in range(P)], float)
        capex_fab += float(sum(EXPANSION[i][int(d.cap_level[i])][1] for i in range(P)))
        capacity = st.capacity + cap_add
        new.capacity = capacity

        # ---- pools de coste del periodo (inflación, volumen, eficiencia) ---------------------------
        new.elab_base = st.elab_base * (1 + ipc); new.energy = st.energy * (1 + ipc)
        new.mult["mp_infl"] = st.mult["mp_infl"] * (1 + ipc)
        new.central = st.central * (1 + ipc); new.general = st.general * (1 + ipc)
        maint = d.maint_pct * (st.af_fab + capex_fab)
        new.eff = st.eff * self.pc.eff_factor(d.maint_pct)
        S = dict(elab_base=new.elab_base, energy=new.energy, eff=new.eff, m=new.mult, pers_unit=None,
                 dep_fab=0.0, gen_fab_now=st.gen_fab * new.mult["gen_fab"])
        units = np.clip(d.occ, 0.0, 1.0) * capacity
        tot_u = max(units.sum(), 1.0)
        new.af_fab = st.af_fab + capex_fab
        S["dep_fab"] = min(DEP_AMT["fab"], st.nbv["fab"]) + R["dep_rate"] * ((st.af_fab - self.cp.af_fab) + R["dep_first_year"] * capex_fab)
        share_cap = capacity / capacity.sum()
        new.pers_pool = st.pers_pool * (1 + ipc); S["pers_unit"] = new.pers_pool

        # ---- diseño / gama / calidad / valor / marca -----------------------------------------------
        design = np.minimum(new.design + np.clip(d.design_up, 0, 1), 10.0)
        value = np.array([self.dm.value_next(i, st.value[i], design[i] - st.design[i], d.gama[i] - st.gama[i], 0.0) for i in range(P)])
        # ESG/otros no afectan. Marca:
        brand = np.array([self.dm.brand_next(i, st.brand[i], d.promo[i]) for i in range(P)])
        cover = self.dm.cover_next(st.cover, d.channel_discount)
        new.design, new.value, new.brand, new.cover, new.gama = design, value, brand, cover, d.gama.copy()

        # ---- demanda, ventas, inventario, obsolescencia --------------------------------------------
        revenue = cogs = nonq = logist = purchases = inv_avg_tot = 0.0
        sales_v = np.zeros(P); inv_end = np.zeros(P); ucost = np.zeros(P); intention = np.zeros(P); expired_val = 0.0
        mult_dem = new.mult["demand"]
        for i in range(P):
            comp = self.pc.unit_components(i, units[i], capacity[i], d.gama[i], design[i], d.quality[i], d.dpo, S, share_cap[i])
            u_c = comp["mp"] + comp["elab"] + comp["energy"] + comp["pers"]      # [INFERIDO] el inventario se valora a coste DIRECTO (6,11 = 6,06 en R1 2º lugar)
            dem = self.dm.demand(i, price[i], brand[i], value[i], cover, el, mac.mkt_idx[i][k], mult_dem) * mac.conv
            if dem_override is not None: dem = float(dem_override[i])      # modo replay/backtest
            # incentivo de ventas: efecto sobre demanda no identificado -> neutro [PENDIENTE]
            inv_b = st.inv_units[i]
            usable_old = min(inv_b, dem * R["h1_share"])
            avail_new = units[i]
            sales = min(dem, usable_old + avail_new)
            sold_old = min(usable_old, sales)
            expired = inv_b - sold_old
            inv_e = units[i] - (sales - sold_old)
            ref_cost = u_c
            revenue += sales * price[i] * (1 - d.channel_discount)
            cogs += sold_old * st.inv_cost[i] + (sales - sold_old) * u_c
            defect = pp[i].defect * new.mult["defect"]; merma = pp[i].merma * new.mult["merma"]
            nonq += expired * st.inv_cost[i] + defect * units[i] * merma * ref_cost
            logist += pp[i].transport * (1 + ipc) * sales
            inv_avg_tot += 0.5 * (inv_b + inv_e)
            purchases += comp["mp"] * units[i]
            expired_val += expired * st.inv_cost[i]
            sales_v[i], inv_end[i], ucost[i], intention[i] = sales, inv_e, u_c, dem
        logist += storage_cost(inv_avg_tot) * new.mult["storage"]
        new.inv_units, new.inv_cost = inv_end, ucost
        inv_value = float(np.sum(inv_end * ucost)) + st.rm_inv
        period_fab = S["dep_fab"] + S["gen_fab_now"]          # depreciación + generales de fábrica: costes del periodo, íntegros a coste de ventas
        cogs += period_fab
        margin = revenue - cogs - nonq - logist

        # ---- gastos de operación -------------------------------------------------------------------
        marketing = float(d.promo.sum())
        personnel = new.central + d.sales_incentive * revenue
        # [DATO] presupuesto de diseño = nivel recurrente: corb 48.000 (N4)->84.001 (N5)->120.002 (N6); buf 32.000 (N3)->74.667->117.333
        design_cost = float(sum(pp[i].design_hold + pp[i].design_climb * max(st.design[i] + np.clip(d.design_up[i], 0, 1) - pp[i].design0 - pp[i].design_free, 0.0)
                                for i in range(P)))
        idi = design_cost + maint
        general = new.general + gasto_proj
        new.dep_other = st.dep_other + R["dep_rate"] * capex_otro
        shortfall = sum(DEP_AMT[a] - min(DEP_AMT[a], st.nbv[a]) for a in ("alm", "cen", "bld", "imm"))     # activos ya totalmente depreciados
        dep_other_exp = st.dep_other + R["dep_rate"] * capex_otro * 1.0 - shortfall
        new.nbv = {a: st.nbv[a] - min(DEP_AMT[a], st.nbv[a]) for a in st.nbv}
        clients = revenue * R["q4_share"] * d.dso / R["cli_days_div"]
        provisions = (clients - st.clients) * R["provision_share"]       # [DATO] dotación = 1/3 de la variación de clientes netos: 2025 -32.922/3 = -10.974; R1 2º lugar +58.451/3 = 19.484
        opex = marketing + personnel + idi + general + dep_other_exp + provisions
        ebit = margin - opex

        # ---- financiación --------------------------------------------------------------------------
        old_princ = self.cp.existing_sched[k] if k < len(self.cp.existing_sched) else st.debt_old
        old_princ = min(old_princ, st.debt_old)
        interest_old = self.cp.existing_rate * (st.debt_old - 0.5 * old_princ)
        new.debt_old = st.debt_old - old_princ
        rate_lp, rate_cp = loan_rate("lp", ref, self.cp.rating0), loan_rate("cp", ref, self.cp.rating0)
        rate_ex = loan_rate("extra", ref, self.cp.rating0)
        tr_int = tr_pr = 0.0; new_tr = []
        for bal, rt, yl in st.tranches:
            i_, p_ = french_split(bal, rt, yl); tr_int += i_; tr_pr += p_; new_tr.append((bal - p_, rt, yl - 1))
        if d.new_lp > 0:
            tr_int += 0.5 * rate_lp * d.new_lp                           # solo medio año de interés en el año de contratación
            new_tr.append((d.new_lp, rate_lp, R["lp_years"]))            # amortización francesa desde el año siguiente
        new.tranches = [t for t in new_tr if t[0] > 1.0]
        cp_repay = st.debt_cp
        interest_cp = rate_cp * (d.new_cp * 0.5 + st.debt_cp * 0.5)
        fin_income = (ref * R["fa_cp_factor"] * d.fa_cp + ref * R["fa_lp_factor"] * d.fa_lp)
        capex = capex_fab + capex_otro
        clients = revenue * R["q4_share"] * d.dso / R["cli_days_div"]
        payables = self.cp.pay_k * purchases * d.dpo / 45.0
        dep_total = S["dep_fab"] + dep_other_exp

        extraord = self.cp.extraordinary[k]
        extra = 0.0
        for _ in range(6):    # punto fijo: el interés del crédito extraordinario depende de su propio saldo
            interest = interest_old + tr_int + interest_cp + rate_ex * extra
            ebt = ebit - interest + fin_income + extraord
            taxable = max(ebt - st.nol, 0.0)
            tax = R["tax_rate"] * taxable
            ni = ebt - tax
            div = d.dividend_pct * max(ni, 0.0)
            cash_pre = (st.cash + ni + dep_total - (clients - st.clients) - (inv_value - st.inv_value)
                        + (payables - st.payables) - capex - (d.fa_cp - st.fa_cp) - (d.fa_lp - st.fa_lp)
                        + d.new_lp - old_princ - tr_pr + (d.new_cp - cp_repay) - div + tax - st.tax_payable)   # el impuesto se devenga hoy (no sale caja) y se paga el año siguiente
            extra = max(-cash_pre, 0.0)
        cash = max(cash_pre, 0.0)
        new.last_units = units.copy(); new.tax_payable = tax
        new.nol = max(st.nol - max(ebt, 0.0), 0.0) if ebt > 0 else st.nol + (-ebt)

        new.cash, new.clients, new.payables = cash, clients, payables
        new.debt_cp, new.fa_cp, new.fa_lp = d.new_cp, d.fa_cp, d.fa_lp
        new.af_gross = st.af_gross + capex + 0.0; new.acc_dep = st.acc_dep + dep_total
        new.equity = st.equity + ni - div
        debt_total = new.debt_old + sum(t[0] for t in new.tranches) + d.new_cp
        cur_lp = (self.cp.existing_sched[k + 1] if k + 1 < len(self.cp.existing_sched) else new.debt_old) if new.debt_old > 0 else 0.0
        cur_lp = min(cur_lp, new.debt_old) + sum(french_split(b, rt, yl)[1] for b, rt, yl in new.tranches)
        assets = (new.af_gross - new.acc_dep) + self.cp.participations + new.fa_cp + new.fa_lp + inv_value + clients + cash
        liabs = new.equity + debt_total + extra + payables + new.tax_payable
        tot_sales = sales_v.sum()
        rep = dict(
            ingresos=revenue, coste_fabricacion=cogs, coste_logistica=logist, coste_no_calidad=nonq, margen=margin,
            gasto_marketing=marketing, gasto_personal=personnel, gasto_id=idi, gasto_generales=general,
            gasto_depreciacion=dep_other_exp, resultado_bruto=ebit, gasto_intereses=interest, ingresos_financieros=fin_income,
            resultado_neto=ni, impuestos=tax,
            activo_fijo_bruto=new.af_gross, dep_acumulada=new.acc_dep, clientes=clients, efectivo=cash, af_cp=new.fa_cp,
            af_lp=new.fa_lp, inventario=inv_value, proveedores=payables, prestamos_cp=cur_lp + d.new_cp,
            prestamos_lp=debt_total - d.new_cp - cur_lp, recursos_propios=new.equity,
            credito_extraordinario=extra, balance_error=assets - liabs, unidades_vendidas=sales_v, intencion=intention,
            inv_ratio=float(inv_end.sum() / max(tot_sales, 1.0)), expired_value=expired_val, ocupacion=units / capacity, ocupacion_planta=float(units.sum() / capacity.sum()),
            roe_plataforma=ni / max(new.equity + EQ_OFFSET, 1.0),
            liquidez=(cash + clients + inv_value + new.fa_cp) / max(payables + old_princ + d.new_cp + extra, 1.0),
            deuda_patrimonio=(debt_total + extra + payables) / max(new.equity, 1.0),
            marca=brand.copy(), valor_producto=value.copy(), cobertura=cover,
            cuota=float(tot_sales / sum(MKT0[i] * mac.mkt_idx[i][k] for i in range(P))),
            precio=price.copy(), unidades=units, cuf=ucost, capex=capex, mantenimiento=maint, eff=new.eff, dep_total=dep_total)
        return new, rep


# ======================================================================
# 5. PROXY DEL VALOR DE LA COMPAÑÍA (manual §7)
# ======================================================================
class ValueModel:
    def __init__(self, comp): self.cp = comp

    def score(self, rep) -> float:
        roe = rep["roe_plataforma"]
        econ = 0.5 * np.tanh(rep["resultado_neto"] / 1.5e6) + 0.5 * np.tanh(roe / 0.15)
        solv = 0.5 / (1.0 + max(rep["deuda_patrimonio"], 0)) + 0.5 * np.tanh(rep["liquidez"] / 2.0)
        sold = np.maximum(np.asarray(rep["unidades_vendidas"], float), 1e-9)
        brand = float(np.dot(rep["marca"], sold) / sold.sum()) / 100.0     # [DATO] indicador de marca = promedio ponderado por unidades (Año 0: 35,0); valor de producto = promedio simple (7,1)
        prod = 0.5 * float(np.mean(rep["valor_producto"])) / 10.0 + 0.5 * rep["cobertura"]
        return (WEIGHTS["econ"] * econ + WEIGHTS["solv"] * solv + WEIGHTS["brand"] * brand
                + WEIGHTS["product"] * prod + WEIGHTS["share"] * rep["cuota"])


# ======================================================================
# 6. CALIBRADORES (presupuestación = 33% del score; demanda se estrecha con la R1)
# ======================================================================
class BudgetCalibrator:
    """Mide error pronóstico vs real por línea y corrige sesgos para la siguiente ronda."""
    def __init__(self, alpha=0.6): self.alpha, self.bias = alpha, {}

    @staticmethod
    def accuracy(forecast: dict, actual: dict, floor=1.0) -> float:
        errs = [min(abs(forecast[k] - actual[k]) / max(abs(actual[k]), floor), 1.0)
                for k in forecast if k in actual and np.isscalar(forecast[k])]
        return 1.0 - float(np.mean(errs))

    def update(self, forecast: dict, actual: dict):
        for k, f in forecast.items():
            if k in actual and np.isscalar(f) and abs(f) > 1e-9:
                self.bias[k] = (1 - self.alpha) * self.bias.get(k, 1.0) + self.alpha * (actual[k] / f)

    def adjust(self, forecast: dict) -> dict:
        return {k: (v * self.bias.get(k, 1.0) if np.isscalar(v) else v) for k, v in forecast.items()}


class DemandCalibrator:
    """Tras cada ronda, filtra la región factible con la INTENCIÓN DE COMPRA real (Cuadro de Mando > Mercado)."""
    def __init__(self): self.obs = []        # (i, price, brand, value, cover, mkt_idx, intention_real)

    def add(self, i, price, brand, value, cover, mkt_idx, intention): self.obs.append((i, price, brand, value, cover, mkt_idx, intention))

    def filter(self, samples, i, prods, comp, tol=0.08):
        p = prods[i]; keep = np.ones(len(samples), bool)
        for (j, pr, b, v, c, m, y) in self.obs:
            if j != i: continue
            pred = p.demand0 * (pr / p.price0) ** samples[:, 0] * (b / p.brand0) ** samples[:, 1] * (v / p.value0) ** samples[:, 2] \
                   * (c / comp.cover0) ** samples[:, 3] * m
            keep &= np.abs(np.log(pred / y)) <= tol
        return samples[keep]


# ======================================================================
# 7. OPTIMIZADOR (continuas: L-BFGS-B robusto sobre escenarios; discretas: búsqueda local)
# ======================================================================
class Optimizer:
    SPEC = [("dprice", P), ("occ", P), ("promo", P), ("gama", P), ("design_up", P), ("maint_pct", 1),
            ("channel_discount", 1), ("sales_incentive", 1), ("dso", 1), ("dpo", 1), ("new_lp", 1),
            ("new_cp", 1), ("fa_cp", 1), ("fa_lp", 1), ("dividend_pct", 1)]

    def __init__(self, prods, comp, state0, horizon=2, first_round=1, kappa=0.4,
                 pen_cash=40.0, pen_inv=15.0, pen_exp=8.0, inv_cap=0.05, min_cash=150_000.0, n_demand_levels=3,
                 allow_debt=False, max_dividend=0.0, explore_levers=False, dprice_cap=0.15, worst_only=False):
        self.dprice_cap, self.worst_only = dprice_cap, worst_only
        self.pp, self.cp, self.st0 = prods, comp, state0
        self.explore_levers = explore_levers
        self.allow_debt, self.max_dividend = allow_debt, max_dividend   # [SUPUESTO] el 2º lugar nunca pidió deuda ni pagó dividendos; efecto en score desconocido
        self.dm, self.pc = MarketDemand(prods, comp), ProductionCosts(prods, comp)
        self.fin, self.vm = Financials(prods, comp, self.dm, self.pc), ValueModel(comp)
        self.H, self.r0 = horizon, first_round
        self.kappa, self.pen_cash, self.pen_inv, self.pen_exp, self.inv_cap, self.min_cash = kappa, pen_cash, pen_inv, pen_exp, inv_cap, min_cash
        dscs = demand_scenarios(n_demand_levels)
        if worst_only: dscs = [dscs[0]]      # nivel más elástico al precio (percentil 20 de la región factible)
        mv = macro_variants()
        # escenarios = combinaciones (elasticidades) x (mercado), con probabilidades
        self.scs = []
        for dk, el in enumerate(dscs):
            for name, mac, pr in mv:
                self.scs.append((f"d{dk}-{name}", el, mac, pr / len(dscs)))
        self.lb, self.ub = self._bounds(); self.n1 = len(self.lb)

    # límites: se mantienen DENTRO del rango observado/sensato para palancas sin efecto identificado
    def _bounds(self):
        pp, lb, ub = self.pp, [], []
        for name, n in self.SPEC:
            for i in range(n):
                p = pp[i] if n == P else None
                lo, hi = {
                    "dprice": (-self.dprice_cap, self.dprice_cap),          # [DATO] el mercado no admite variaciones de precio >15% entre periodos
                    
                    "occ": (0.30, 1.0),             # el 60% se exige a nivel PLANTA TOTAL (penalización en objective), no por producto
                     "promo": (0.5 * p.promo_base, 3.0 * p.promo_base) if p else 0,
                    "gama": (1.0, float(RULES["gama_max"][i])), "design_up": (0.0, 1.0),
                    "maint_pct": (0.02, 0.045),      # observado hasta 4,0% (2º lugar); no extrapolar
                     "channel_discount": (0.12, 0.18) if self.explore_levers else (0.15, 0.15 + 1e-9),   # CONGELADO: efecto sobre cobertura = [SUPUESTO]
                    "sales_incentive": (0.02, 0.05) if self.explore_levers else (0.035, 0.035 + 1e-9),  # CONGELADO: efecto sobre ventas no identificado
                    "dso": (35.0, 60.0) if self.explore_levers else (45.0, 45.0 + 1e-9), "dpo": (35.0, 60.0) if self.explore_levers else (45.0, 45.0 + 1e-9),   # [DATO panel] 45/45 en 2025; efecto en competitividad no cuantificado -> congelado
                    "new_lp": (0.0, 1.5e6 if self.allow_debt else 0.0), "new_cp": (0.0, 5e5 if self.allow_debt else 0.0),
                    "fa_cp": (0.0, 5.0e5), "fa_lp": (0.0, 1.2e6), "dividend_pct": (0.0, self.max_dividend),   # [DATO panel] CP hasta 500.000 por trimestre; LP hasta 1.200.000
                }[name]
                lb.append(lo); ub.append(max(hi, lo + 1e-9))
        return np.array(lb), np.array(ub)

    def decode(self, x01, disc, r_idx) -> Decisions:
        x = self.lb + np.clip(x01[r_idx * self.n1:(r_idx + 1) * self.n1], 0, 1) * (self.ub - self.lb)
        out, k = {}, 0
        for name, n in self.SPEC:
            out[name] = x[k:k + n].copy() if n > 1 else float(x[k]); k += n
        rr = self.r0 + r_idx
        return Decisions(quality=disc["quality"].copy(), cap_level=np.array(disc["cap"].get(rr, np.zeros(P))),
                         projects=tuple(disc["proj"].get(rr, ())), **out)

    def simulate(self, x01, disc, sc):
        name, el, mac, pr = sc; st, reps = copy.deepcopy(self.st0), []
        for r in range(self.H):
            dec = self.decode(x01, disc, r)
            new, rep = self.fin.step(st, dec, mac, el, self.r0 + r)
            st = new; reps.append(rep)
        return reps

    def objective(self, x01, disc):
        vals, nis, ws = [], [], np.linspace(1.0, 2.0, self.H); ws = ws / ws.sum()
        for sc in self.scs:
            reps = self.simulate(x01, disc, sc); J = 0.0
            for w, rep in zip(ws, reps):
                J += w * (self.vm.score(rep) + 0.05 * np.tanh(rep["resultado_neto"] / 1.5e6)
                          - self.pen_cash * max(rep["credito_extraordinario"] + max(self.min_cash - rep["efectivo"], 0) * 0.2, 0) / 1e6
                          - self.pen_inv * max(rep["inv_ratio"] - self.inv_cap, 0.0) ** 2
                          - self.pen_exp * rep["expired_value"] / 1e6
                          - 200.0 * max(0.60 - rep["ocupacion_planta"], 0.0) ** 2)   # [DATO] <60% ocupación planta -> gastos por despido (conservador)
            vals.append(J); nis.append(reps[0]["resultado_neto"])
        pr = np.array([s[3] for s in self.scs]); pr = pr / pr.sum()
        mean = float(np.dot(pr, vals))
        risk = float(np.sqrt(np.dot(pr, (np.array(nis) - np.dot(pr, nis)) ** 2))) / 1.5e6
        return -(mean - self.kappa * risk)

    def _solve_cont(self, disc, x0, maxiter):
        res = minimize(self.objective, x0, args=(disc,), method="L-BFGS-B", bounds=[(0, 1)] * len(x0),
                       options=dict(maxiter=maxiter, maxfun=maxiter * (len(x0) + 2)))
        return res.fun, res.x

    def default_disc(self): return dict(quality=np.zeros(P), cap={}, proj={})

    def solve(self, n_starts=2, maxiter=25, discrete_pass=True, seed=0, verbose=True, allow_cap=True):
        rng = np.random.default_rng(seed); disc = self.default_disc()
        best_f, best_x = np.inf, None
        for s in range(n_starts):
            x0 = rng.uniform(0.35, 0.65, self.n1 * self.H)
            f, x = self._solve_cont(disc, x0, maxiter)
            if f < best_f: best_f, best_x = f, x
        if verbose: print(f"  [continuas] objetivo={-best_f:.4f}")
        if discrete_pass:
            options = []
            for rr in range(self.r0, self.r0 + self.H):
                for nm, pj in PROJECTS.items():
                    if pj["r"] == rr and pj.get("known", True): options.append(("proj", rr, nm))
                for i in range(P):
                    for lv in ((1, 2) if allow_cap else ()): options.append(("cap", rr, (i, lv)))
            for i in range(P):
                for q in (1, 2): options.append(("qual", 0, (i, q)))
            for kind, rr, val in options:
                cand = copy.deepcopy(disc)
                if kind == "proj":
                    cur = list(cand["proj"].get(rr, ()))
                    if val in cur: continue
                    cand["proj"][rr] = tuple(cur + [val])
                elif kind == "cap":
                    i, lv = val; arr = np.array(cand["cap"].get(rr, np.zeros(P))); 
                    if arr[i] == lv: continue
                    arr[i] = lv; cand["cap"][rr] = arr
                else:
                    i, q = val
                    if cand["quality"][i] == q: continue
                    cand["quality"][i] = q
                f, x = self._solve_cont(cand, best_x, max(maxiter // 2, 8))
                if f < best_f - 1e-6:
                    best_f, best_x, disc = f, x, cand
                    if verbose: print(f"  [discreta] acepta {kind} r{rr} {val} -> objetivo={-best_f:.4f}")
        decs = [self.decode(best_x, disc, r) for r in range(self.H)]
        reps = self.simulate(best_x, disc, self.scs[0])
        return dict(objective=-best_f, decisions=decs, forecast=reps, discrete=disc, x=best_x)


# ======================================================================
# 8. BACKTEST Y UTILIDADES
# ======================================================================
def backtest_year0():
    """Reproduce el coste unitario de fabricación del Año 0 y compara con el Excel (columna 2024)."""
    pp, comp = year0_products(), Company(); pc = ProductionCosts(pp, comp)
    st = initial_state(pp, comp); units = np.array([195000, 25000, 28000], float); dep = np.array([135000, 19800, 25200]); gen = np.array([118250, 16500, 22000])
    expected = dict(elab=(1.645, 2.597, 0.247), cuf=(8.637, 14.778, 3.193))   # CUF real RealMan 2025 = (MP+elab+energía+personal+dep+gen)/producidas
    print("Backtest Año 0 (Excel 'Producción' col. 2024):")
    S = dict(elab_base=st.elab_base, energy=st.energy, eff=1.0, m=st.mult, pers_unit=st.pers_pool, dep_fab=180000.0, gen_fab_now=156750.0)
    share = np.array([p.cap0 for p in pp]); share = share / share.sum()
    for i in range(P):
        c = pc.unit_components(i, units[i], pp[i].cap0, pp[i].gama0, pp[i].design0, 0, 45, S, share[i])
        # usar imputación exacta del Excel para dep/gen en este test
        cuf = c["mp"] + c["elab"] + c["energy"] + c["pers"] + dep[i] / units[i] + gen[i] / units[i]
        print(f"  {pp[i].name:10s} elaboración={c['elab']:.3f} (Excel {expected['elab'][i]})  "
              f"CUF={cuf:.3f} (Excel {expected['cuf'][i]})  err={cuf - expected['cuf'][i]:+.3f}")
    print(f"  patrimonio neto inicial = {st.equity:,.0f}  (Excel: 3.733.349)")
    # uniformidad del factor de eficiencia 2025 (si las tablas son correctas, debe ser igual en los 3 productos)
    base25 = (1.33, 2.18, 0.20); gam25 = (21, 9, 5); des25 = (5, 4, 4); occ25 = (1.0, 0.9, 0.7); real25 = (1.13, 1.78, 0.17)
    f = [real25[i] / (base25[i] * pc.f_occ(occ25[i]) * pc.f_gama(i, gam25[i]) * pc.f_design(des25[i])) for i in range(P)]
    print(f"  Factor de eficiencia observado 2025 (debe ser ~igual): {np.round(f, 3)}  -> 2º lugar subió mantenimiento 2,6% -> 4,0%")


def replay_second_place_r1():
    """Reproduce la RONDA 1 (2025) del 2º lugar con sus decisiones reales y compara con sus resultados reales.
    Las ventas se fuerzan a las reales (estaba limitado por capacidad). Valida costes, gastos, impuestos y balance."""
    pp, comp = year0_products(), Company(extraordinary=(408_000.0, 0, 0, 0)); st0 = initial_state(pp, comp)
    fin = Financials(pp, comp, MarketDemand(pp, comp), ProductionCosts(pp, comp))
    dec = Decisions(price=np.array([18.4, 30.2, 3.05]), occ=np.array([235000 / 235000, 34200 / 38000, 28000 / 40000]),
                    promo=np.array([85000., 130000., 48000.]), gama=np.array([21., 9., 5.]), design_up=np.ones(P),
                    maint_pct=0.04, channel_discount=0.15, sales_incentive=0.035, dso=40.0, dpo=50.0,
                    new_lp=0.0, new_cp=0.0, fa_cp=125_000., fa_lp=450_000., dividend_pct=0.0,
                    quality=np.zeros(P), cap_level=np.array([1, 1, 0]),
                    projects=("proceso_productivo", "eficiencia_energetica", "nuevos_proveedores"))
    new, rep = fin.step(st0, dec, Macro(), np.zeros((P, 4)), 1, dem_override=[234222, 33981, 28001])
    real = dict(ingresos=4608047, coste_fabricacion=2256490, coste_logistica=64505, coste_no_calidad=66662, margen=2220390,
                gasto_marketing=263000, gasto_personal=704443, gasto_id=323868, gasto_generales=146472, gasto_depreciacion=148000,
                resultado_bruto=615123, gasto_intereses=55673, ingresos_financieros=32317, impuestos=125576,
                clientes=385486, efectivo=1749370, inventario=78584, proveedores=249224, activo_fijo_bruto=6035000,
                dep_acumulada=2917500, recursos_propios=3733349 + 874192)
    print("Replay Ronda 1 del 2º lugar (decisiones reales -> twin vs real):")
    print(f"  {'línea':22s}{'twin':>14s}{'real':>14s}{'error':>9s}")
    for k, v in real.items():
        t = rep[k]; err = (t - v) / abs(v) if v else 0
        flag = "" if abs(err) < 0.05 else ("  <- revisar" if abs(err) < 0.15 else "  <<< DESVÍO")
        print(f"  {k:22s}{t:14,.0f}{v:14,.0f}{err:9.1%}{flag}")
    print(f"  error de cuadre del balance del twin = {rep['balance_error']:.4f}")
    return rep


PENDIENTES = [
    ("R1 · Tarjetas con importe vacío", "Nuevos proveedores, calidad producto, condiciones laborales, código de conducta, ESG, edificio y capital VC muestran 0/--: abrir de nuevo o confirmar importes."),
    ("R1 · Terreno agrícola", "Pérdida declarada 50.000 vs 110.000 (375.000-265.000). Decisión única del equipo; el twin no la adopta."),
    ("R1 · Proyectos limitados", "Eficiencia energética y proceso productivo: solo las 3 primeras solicitudes -> enviar la decisión cuanto antes."),
    ("Cuadro de Mando > Mercado", "Intención de compra exacta Año 0 por producto (hoy 225k / 29k / 33k)."),
    ("Resultados extraordinarios", "Origen de los 408.000 del 2º lugar en R1/R2; hoy se asume el ingreso del Año 0 sin terreno."),
    ("Balance > Rating", "Mapa rating -> % sobre el tipo (solo se conoce 59,8 -> +20,4%)."),
    ("R1 · Competidores", "Tras R1: precios, marca y valor de las otras 6 compañías para modelar competencia."),
    ("Palancas congeladas", "Descuento canal 15%, incentivo 3,5%, DSO/DPO 40-50: sin evidencia de su efecto."),
    ("Ocupación 60%", "Texto dice 'se pueden generar' gastos; el twin lo trata como restricción conservadora a nivel planta."),
]


def budget_form(rep, st_prev=None):
    """Valores para el formulario Presupuestar (mismas líneas que la plataforma)."""
    f = lambda k: round(float(rep[k]))
    return {
        "Ingresos": f("ingresos"), "Coste Fabricación": f("coste_fabricacion"), "Logística Externa": f("coste_logistica"),
        "No calidad": f("coste_no_calidad"), "Gastos Marketing": f("gasto_marketing"), "Personal": f("gasto_personal"),
        "I+D": f("gasto_id"), "Generales": f("gasto_generales"), "Depreciación": f("gasto_depreciacion"),
        "Gastos por Intereses": f("gasto_intereses"), "Ingresos Financieros": f("ingresos_financieros"),
        "Activo Fijo Bruto": f("activo_fijo_bruto"), "Depreciación Acumulada": f("dep_acumulada"),
        "Clientes": f("clientes"), "Efectivo": f("efectivo"), "Activos Financieros CP": f("af_cp"),
        "Activos Financieros LP": f("af_lp"), "Inventario": f("inventario"), "Proveedores": f("proveedores"),
        "Préstamos CP": f("prestamos_cp"), "Préstamos LP": f("prestamos_lp"),
        "Resultado Neto": f("resultado_neto"),
    }


def show_pendientes():
    print("DATOS A LEER DE LA PLATAFORMA (en orden de impacto):")
    for k, (a, b) in enumerate(PENDIENTES, 1): print(f"  {k}. {a}: {b}")


def demand_report():
    print("Región factible de elasticidades (percentiles 5/50/95) — modelo log-lineal vs observaciones del 2º lugar")
    for i in range(P):
        S = feasible_demand_params(i)
        print(f"  {PRODUCTS[i]:10s} muestras factibles: {len(S)}")
        if len(S):
            for n, j in zip(("e_precio", "e_marca", "e_valor", "e_cobertura"), range(4)):
                print(f"     {n:12s}", np.percentile(S[:, j], [5, 50, 95]).round(2))
    print("  Lectura: corbatas está bien acotado; bufandas/calcetines casi vacío = hay efecto competencia que el modelo no captura.")


def show_plan(out, prods=None):
    prods = prods or year0_products()
    for r, (dec, rep) in enumerate(zip(out["decisions"], out["forecast"]), 1):
        print(f"\n=== Ronda {r}  (proyectos: {dec.projects or '-'}, capacidad: {dec.cap_level.tolist()}, calidad MP: {[('económica','estándar','premium')[int(q)] for q in dec.quality]})")
        for i in range(P):
            print(f"  {PRODUCTS[i]:10s} precio={rep['precio'][i]:7.2f} ({dec.dprice[i]:+.1%})  producir={rep['unidades'][i]:9,.0f} (ocup {rep['ocupacion'][i]:.0%})  "
                  f"promo={dec.promo[i]:9,.0f}  gama={dec.gama[i]:4.1f}  diseño+{dec.design_up[i]:.2f}  "
                  f"vende={rep['unidades_vendidas'][i]:9,.0f}  intención={rep['intencion'][i]:9,.0f}  marca={rep['marca'][i]:4.0f}")
        print(f"  mant={dec.maint_pct:.2%}  desc.canal={dec.channel_discount:.1%}  incentivo={dec.sales_incentive:.1%}  DSO={dec.dso:.0f}  DPO={dec.dpo:.0f}"
              f"  nuevo LP={dec.new_lp:,.0f}  CP={dec.new_cp:,.0f}  AF CP={dec.fa_cp:,.0f}  AF LP={dec.fa_lp:,.0f}  div={dec.dividend_pct:.0%}")
        print("  PRESUPUESTAR:", budget_form(rep))
        print(f"  ocup. planta={rep['ocupacion_planta']:.0%}  ingresos={rep['ingresos']:,.0f}  margen={rep['margen']:,.0f}  rdo.neto={rep['resultado_neto']:,.0f}  caja={rep['efectivo']:,.0f}  "
              f"créd.extra={rep['credito_extraordinario']:,.0f}  inv/ventas={rep['inv_ratio']:.1%}  error balance={rep['balance_error']:.2f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    if cmd == "backtest": backtest_year0()
    elif cmd == "demand": demand_report()
    elif cmd == "replay": replay_second_place_r1()
    elif cmd == "pendientes": show_pendientes()
    elif cmd == "solve":
        H = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        pp, comp = year0_products(), Company(); st0 = initial_state(pp, comp)
        cons = len(sys.argv) > 3 and sys.argv[3] == "cons"      # python twin.py solve 1 cons
        opt = Optimizer(pp, comp, st0, horizon=H, first_round=1, dprice_cap=0.05 if cons else 0.15, worst_only=cons)
        out = opt.solve(n_starts=2, maxiter=20, allow_cap=('nocap' not in sys.argv))
        show_plan(out, pp)
