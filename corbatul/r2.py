# -*- coding: utf-8 -*-
"""Gemelo de la Ronda 2 calibrado con los datos REALES de la R1 (RealMan) y con la R2 real del ganador de la
edición anterior (mismo punto de partida). Pensado para PRESUPUESTAR: cada línea sigue una regla verificada.

    python -m corbatul.r2            # plan recomendado, presupuesto y Monte Carlo

Reglas verificadas (R1 real, euro a euro o <1 %):
  ventas      = (producción + inventario inicial) / (1 + 2,32 %) cuando la demanda supera a la oferta
  ingresos    = ventas × precio × (1 − descuento canal)
  transporte  = ventas × tarifa (R2: 0,21 / 0,17 / 0,13, R2 real del ganador)
  almacenaje  = 0,30 × suma de inventarios al cierre de los 4 trimestres (≈ 4 × inventario final)
  personal    = 543.162 × (1 + IPC 2,7 %) + 3,5 % × ingresos        (557.827 exacto en la R2 del ganador)
  generales   = 146.472 × (1 + IPC)  [150.427 exacto en la R2 del ganador]; RealMan tuvo +48.336 sin explicar en R1
  mantenimiento = 4 % × activo de fábrica;  depreciación fábrica = 10 % × activo de fábrica (R2 real ganador)
  dotación    = (clientes final − clientes inicial) / 3
  clientes    = ingresos T4 × DSO / 120 (exacto con 45 días)
  impuesto    = 25 % (las pérdidas compensables se agotaron en R1)
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
import numpy as np
from . import twin as T

DATA = Path(__file__).resolve().parent.parent / "data"
N = ("Corbatas", "Bufandas", "Calcetines")
IPC = 0.027                     # [DATO] macro 2027 (personal de central 543.162 → 557.827 en la R2 real del ganador)
REF_RATIO = 3.3 / 4.9           # [DATO] tipo de referencia 2027 / 2026: ingresos financieros 32.317 → 22.072 en el ganador (×0,683)

# ---------- punto de partida: cierre real R1 de RealMan ----------
R1 = dict(
    ventas=np.array([234225, 35739, 31908.]), intencion=np.array([366000, 62000, 50000.]),
    precio=np.array([18.40, 30.20, 3.04]), marca=np.array([44, 38, 32.]), valor=np.array([9.6, 8.4, 7.7]),
    capacidad=np.array([235000, 38000, 40000.]), ocupacion=np.array([1.0, 0.947, 0.80]),
    gama=np.array([21, 9, 5.]), diseno=np.array([5, 4, 4.]),
    inv_u=np.array([5441, 834, 741.]), inv_valor=45826.0 + 42445.0,     # producto terminado + materia prima
    # coste unitario real por unidad producida (Cuadro de Mando, producción R1)
    mp=np.array([1.700, 4.749, 0.473]), elab=np.array([1.1286, 1.8183, 0.1798]),
    energia=np.array([0.2970, 0.4180, 0.0846]), personal=np.array([3.260, 5.070, 0.610]),
    no_calidad=np.array([0.2140, 0.5010, 0.0761]),
    gen_fab=156750.0, activo_fab=2530000.0, innovacion=222668.0,
    central=543162.0, generales=146472.0,          # generales «normales» (IPC); el real fue 194.808
    clientes=370656.0, proveedores=265899.0, efectivo=1028404.0, impuesto_pendiente=15116.0,
    af_neto=2915000.0, participaciones=305000.0, fa_lp=950000.0, fa_cp=125000.0, patrimonio=4276162.0,          # contable (la plataforma muestra +246.390)
   
    prestamo_lp=927406.0, prestamo_cp=297748.0, ingresos_fin=62917.0,
)
# R2 real del ganador de la edición anterior / su R1 real (mismo punto de partida, mismos 4 proyectos y gama 23/11/5, diseño +1)
SMART = dict(elab=np.array([0.91 / 1.13, 1.40 / 1.78, 0.14 / 0.17]), energia=np.array([0.31 / 0.30, 0.42 / 0.40, 1.0]),
             personal=np.array([2.97 / 3.26, 4.56 / 5.07, 0.57 / 0.61]),
             no_calidad=np.array([0.142 / 0.205, 0.2615 / 0.484, 0.0466 / 0.0673]),
             gama=np.array([23, 11, 5.]), diseno=np.array([6, 5, 4.]), ocupacion=np.array([1.0, 1.0, 0.7]),
             marca=np.array([56, 52, 39.]), valor=np.array([10.0, 10.0, 8.1]), promo=np.array([170000, 150000, 50000.]),
             innovacion=301335.0, gen_fab=144210.0, gastos_fin_deuda_vieja=40525.0)
TRANSPORTE = np.array([0.21, 0.17, 0.13])
AMPLIACION = {0: [(0, 0), (20000, 140000), (40000, 320000), (60000, 750000)],
              1: [(0, 0), (8000, 120000), (17000, 220000), (45000, 450000)],
              2: [(0, 0), (35000, 130000), (50000, 170000), (125000, 450000)]}
PROYECTOS = {   # inversión, dónde va, efecto
    "digitalizacion": dict(inv=125000, activo="fabrica"),       # −8 % personal de producción, +1 diseño
    "automatizacion": dict(inv=125000, activo="otro"),          # hasta +8 % demanda; menos errores
    "layout":         dict(inv=0, activo="gasto"),              # tarjeta: 0 $; ganador R2: generales 150.427 = IPC exacto (sin coste) y −8 % generales de fábrica (144.210)
    "patronaje":      dict(inv=0, activo="otro"),               # tarjeta: 0 $ y reducción «0»; sin efecto asumido
}


@dataclass
class PlanR2:
    precio: list = field(default_factory=lambda: [20.0, 31.5, 3.5])
    nivel_ampliacion: list = field(default_factory=lambda: [2, 2, 0])
    produccion_pct: list = field(default_factory=lambda: [1.0, 1.0, 1.0])
    promocion: list = field(default_factory=lambda: [170000, 150000, 50000])
    gama: list = field(default_factory=lambda: [23, 11, 5])
    proyectos: list = field(default_factory=lambda: ["digitalizacion", "automatizacion", "layout", "patronaje"])
    descuento: float = 0.15
    incentivo: float = 0.035
    dso: float = 45.0
    dpo: float = 45.0
    nuevo_lp: float = 500000.0
    tipo_lp: float = 0.066
    compra_fa_lp: float = 0.0
    extraordinario: float = 18000.0
    generales_extra: float = 0.0        # poner 48.336 para repetir el cargo no explicado de R1
    calidad_mp: list = field(default_factory=lambda: [0, 0, 0])      # 0 económica · 1 estándar · 2 premium
    coste_mp: list = None               # coste base por calidad tal como lo muestra la plataforma para la R2 [[eco,est,pre] x3]


def f_occ(o): return 1.0 + float(np.interp(o, T.OCC_X, T.OCC_Y))
def f_gama(i, g): return float(np.interp(g, T.GAMA_X, T.GAMA_Y[i]))
def f_dis(d): return float(np.interp(d, T.DESIGN_X, T.DESIGN_Y))


def costes_unitarios(p: PlanR2, ocup):
    pj = set(p.proyectos); dis = R1["diseno"] + (1 if "digitalizacion" in pj else 0)
    elab = np.array([R1["elab"][i] * SMART["elab"][i] * f_occ(ocup[i]) / f_occ(SMART["ocupacion"][i])
                     * f_gama(i, p.gama[i]) / f_gama(i, SMART["gama"][i]) * f_dis(dis[i]) / f_dis(SMART["diseno"][i]) for i in range(3)])
    if "layout" not in pj: elab = elab / 0.92
    pers = R1["personal"] * SMART["personal"] * (1.0 if "digitalizacion" in pj else 1 / 0.92)
    energia = R1["energia"] * SMART["energia"]
    mp = R1["mp"].copy()                                            # [DATO R1] MP a precio de lista, sin inflación
    if p.coste_mp is not None:                                      # tabla «Nivel de costes base de materia prima» de la R2
        carga = R1["mp"] / np.array([1.70, 4.60, 0.45])             # carga por unidad observada en R1 (1,00 / 1,032 / 1,051)
        mp = np.array([p.coste_mp[i][int(p.calidad_mp[i])] for i in range(3)]) * carga
    nocal = R1["no_calidad"] * (SMART["no_calidad"] if "automatizacion" in pj else 1.0)
    return dict(mp=mp, elab=elab, energia=energia, personal=pers, no_calidad=nocal, diseno=dis)


def demanda(p: PlanR2, el=None, shock=None, marca=None, valor=None):
    """Intención de compra R2 = intención real R1 × efecto precio × marca × valor (elasticidades de la región factible,
    efecto marca/valor amortiguado 50 % porque la competencia también mejora) × automatización × shock de mercado."""
    el = np.asarray(el if el is not None else [[-3.04, .97, 1.6, 1.02], [-3.25, .08, 1.24, .36], [-.69, .04, .41, .2]], float)
    marca = np.asarray(marca if marca is not None else SMART["marca"]); valor = np.asarray(valor if valor is not None else SMART["valor"])
    pr = np.asarray(p.precio, float)
    f = (pr / R1["precio"]) ** el[:, 0] * ((marca / R1["marca"]) ** el[:, 1]) ** 0.5 * ((valor / R1["valor"]) ** el[:, 2]) ** 0.5
    auto = 1.04 if "automatizacion" in p.proyectos else 1.0       # mitad del +8 % prometido
    return R1["intencion"] * f * auto * (1.0 if shock is None else np.asarray(shock))


def simular(p: PlanR2, dem=None) -> dict:
    cap = R1["capacidad"] + np.array([AMPLIACION[i][p.nivel_ampliacion[i]][0] for i in range(3)])
    capex_cap = float(sum(AMPLIACION[i][p.nivel_ampliacion[i]][1] for i in range(3)))
    prod = np.round(cap * np.asarray(p.produccion_pct, float))
    ocup = prod / cap
    cu = costes_unitarios(p, ocup)
    dem = demanda(p) if dem is None else np.asarray(dem, float)
    oferta = (prod + R1["inv_u"]) / 1.0232
    ventas = np.minimum(dem, oferta); inv_u = prod + R1["inv_u"] - ventas
    precio = np.asarray(p.precio, float)
    ing_p = ventas * precio * (1 - p.descuento); ingresos = float(ing_p.sum())
    # activos y depreciación
    pj = set(p.proyectos)
    capex_fab = capex_cap + sum(PROYECTOS[k]["inv"] for k in pj if PROYECTOS[k]["activo"] == "fabrica")
    capex_otro = sum(PROYECTOS[k]["inv"] for k in pj if PROYECTOS[k]["activo"] == "otro")
    gasto_proy = sum(PROYECTOS[k]["inv"] for k in pj if PROYECTOS[k]["activo"] == "gasto")
    activo_fab = R1["activo_fab"] + capex_fab
    dep_fab = 0.10 * activo_fab
    gen_fab = R1["gen_fab"] * (0.92 if "layout" in pj else 1.0)
    # costes de fabricación (producción) y coste de ventas
    directo_u = cu["mp"] + cu["elab"] + cu["energia"] + cu["personal"]
    fab_prod = float((directo_u * prod).sum()) + dep_fab + gen_fab
    inv_val_pt = float((inv_u * directo_u).sum()); inv_mp = float((cu["mp"] * prod).sum()) * 0.0725
    inv_valor = inv_val_pt + inv_mp
    coste_fab_ventas = fab_prod - (inv_valor - R1["inv_valor"])
    transporte = float((ventas * TRANSPORTE).sum()); almacen = 0.30 * 4 * float(inv_u.sum())
    no_calidad = float((cu["no_calidad"] * prod).sum())
    margen = ingresos - coste_fab_ventas - transporte - almacen - no_calidad
    # gastos de operación
    marketing = float(sum(p.promocion))
    personal = R1["central"] * (1 + IPC) + p.incentivo * ingresos
    innov = SMART["innovacion"] if "digitalizacion" in pj else R1["innovacion"]
    id_ = innov + 0.04 * activo_fab
    dep_otro = 34000 + 55000 + 11250 + 14000 + 0.10 * capex_otro      # edificios, central, almacén (le quedan 11.250), inmaterial
    clientes = ingresos / 4 * p.dso / 120.0
    dotacion = (clientes - R1["clientes"]) / 3.0
    generales = R1["generales"] * (1 + IPC) + gasto_proy + p.generales_extra
    opex = marketing + personal + id_ + dep_otro + dotacion + generales
    bruto = margen - opex
    # financiero
    ing_fin = R1["ingresos_fin"] * REF_RATIO + (p.compra_fa_lp * 0.0604 * REF_RATIO)
    cuota_lp = p.nuevo_lp * p.tipo_lp / (1 - (1 + p.tipo_lp) ** -8) if p.nuevo_lp > 0 else 0.0
    gastos_fin = SMART["gastos_fin_deuda_vieja"] + 0.5 * p.tipo_lp * p.nuevo_lp     # medio año de interés el primer año [SUPUESTO]
    neto_ai = bruto + ing_fin - gastos_fin + p.extraordinario
    impuesto = 0.25 * max(neto_ai, 0.0)
    neto = neto_ai - impuesto
    # balance
    prov = 0.968 * float((directo_u * prod).sum()) * p.dpo / 360.0
    capex = capex_fab + capex_otro
    amort_vieja = R1["prestamo_cp"]; prox_cuota_vieja = R1["prestamo_cp"] * 1.0513
    caja = (R1["efectivo"] + neto + dep_fab + dep_otro - (clientes - R1["clientes"]) - (inv_valor - R1["inv_valor"])
            + (prov - R1["proveedores"]) - capex - p.compra_fa_lp + p.nuevo_lp - amort_vieja + impuesto - R1["impuesto_pendiente"])
    caja_t1 = (R1["efectivo"] - capex - p.compra_fa_lp - R1["impuesto_pendiente"] + p.nuevo_lp - amort_vieja / 4
               + (neto + impuesto * 0 + dep_fab + dep_otro) / 4 - (clientes - R1["clientes"]))
    af_neto = R1["af_neto"] + capex - dep_fab - dep_otro
    deuda_vieja = R1["prestamo_lp"]; cp_vieja = min(prox_cuota_vieja, deuda_vieja)
    cp_nueva = cuota_lp - p.nuevo_lp * p.tipo_lp if p.nuevo_lp > 0 else 0.0
    activo = af_neto + R1["participaciones"] + R1["fa_lp"] + p.compra_fa_lp + R1["fa_cp"] + inv_valor + clientes + caja
    patrimonio = R1["patrimonio"] + neto
    pasivo = (deuda_vieja - cp_vieja + p.nuevo_lp - cp_nueva) + (cp_vieja + cp_nueva) + impuesto + prov
    pyg = [("Ingresos totales", ingresos), ("Costes de fabricación", coste_fab_ventas), ("Costes logística externa", transporte + almacen),
           ("Costes de no calidad", no_calidad), ("Margen de contribución", margen), ("Gastos de marketing", marketing),
           ("Gastos de personal", personal), ("Gastos I+D", id_), ("Gastos de depreciación", dep_otro), ("Dotaciones por insolvencias", dotacion),
           ("Gastos generales", generales), ("Total gastos", opex), ("Resultado bruto", bruto), ("Ingresos financieros", ing_fin),
           ("Gastos financieros", gastos_fin), ("Resultado financiero", ing_fin - gastos_fin), ("Resultado extraordinario", p.extraordinario),
           ("Resultado neto (antes de impuestos)", neto_ai), ("Impuestos", impuesto), ("Resultado después de impuestos", neto)]
    bal = [("Activo fijo bruto", 5810000 + capex), ("Depreciación acumulada", 2895000 + dep_fab + dep_otro), ("Activo fijo neto", af_neto),
           ("Participaciones", R1["participaciones"]), ("Activos financieros LP", R1["fa_lp"] + p.compra_fa_lp), ("Activos financieros CP", R1["fa_cp"]),
           ("Inventario", inv_valor), ("Clientes", clientes), ("Efectivo", caja), ("Activo total", activo),
           ("Capital", 2802686), ("Reservas", 1473476.0), ("Resultado después de impuestos", neto), ("Patrimonio neto", patrimonio),
           ("Préstamo LP", deuda_vieja - cp_vieja + p.nuevo_lp - cp_nueva), ("Préstamo CP", cp_vieja + cp_nueva), ("Crédito extraordinario", 0.0),
           ("Impuestos pendientes de pago", impuesto), ("Proveedores", prov), ("Patrimonio neto + pasivo", patrimonio + pasivo)]
    return dict(capacidad=cap, produccion=prod, demanda=dem, ventas=ventas, inventario_u=inv_u, ingresos_producto=ing_p,
                costes_unitarios={k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in cu.items()},
                pyg=pyg, balance=bal, neto=neto, neto_ai=neto_ai, caja=caja, caja_t1=caja_t1, cuadre=activo - (patrimonio + pasivo),
                capex=capex, gasto_proyectos=gasto_proy, margen_pct=margen / ingresos if ingresos else 0.0)


def muestras(n=4000, seed=7, sigma=0.12):
    """Elasticidades conjuntas de la región factible + shock de mercado lognormal (competencia, conversión)."""
    from .montecarlo import region_factible
    rng = np.random.default_rng(seed); R = region_factible()
    el = np.stack([R[i][rng.integers(0, len(R[i]), n)] for i in range(3)], axis=1)   # (n,3,4)
    shock = np.exp(rng.normal(-sigma ** 2 / 2, sigma, (n, 3)))
    return el, shock


def evaluar(p: PlanR2, el, shock):
    dems = np.stack([demanda(p, el[k], shock[k]) for k in range(len(el))])
    netos = np.array([simular(p, d)["neto"] for d in dems])
    base = simular(p, np.full(3, 1e9))           # presupuesto: se vende toda la oferta
    oferta = base["ventas"]
    p_corto = (dems < oferta * 0.995).mean(axis=0)
    return dict(neto_medio=float(netos.mean()), p5=float(np.percentile(netos, 5)), p50=float(np.median(netos)),
                presupuesto=base["neto"], desvio_medio=float(np.abs(netos - base["neto"]).mean()),
                prob_demanda_corta=p_corto.tolist(), caja_t1=base["caja_t1"])


def optimizar(n=1500):
    el, shock = muestras(n)
    best = None; filas = []
    for lc in (0, 1, 2):
        for lb in (0, 1, 2):
            for pc in np.arange(19.0, 24.01, 0.5):
                for pb in np.arange(30.0, 36.01, 1.0):
                    for pk in (3.5, 4.0, 4.3):
                        p = PlanR2(precio=[float(pc), float(pb), pk], nivel_ampliacion=[lc, lb, 0])
                        dems = np.stack([demanda(p, el[k], shock[k]) for k in range(len(el))])
                        ofer = (R1["capacidad"] + np.array([AMPLIACION[0][lc][0], AMPLIACION[1][lb][0], 0]) + R1["inv_u"]) / 1.0232
                        pc_ = (dems < ofer * 0.995).mean(axis=0)
                        filas.append((lc, lb, pc, pb, pk, pc_))
    return filas


if __name__ == "__main__":
    p = PlanR2(); r = simular(p, np.full(3, 1e9))
    for k, v in r["pyg"]: print(f"  {k:36s} {v:>14,.0f}")
    print("cuadre balance", round(r["cuadre"], 2), "caja T1", round(r["caja_t1"]), "caja fin", round(r["caja"]))
