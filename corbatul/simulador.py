# -*- coding: utf-8 -*-
"""Simulación determinista de la R1 con decisiones ajustadas (what-if) y comparación contra el plan."""
from __future__ import annotations
import numpy as np
from . import twin as T
from .plan import (load_plan, sanear, decisions_from_plan, motor, el_medio, capacidad, NOMBRES, P, EXTRA_ALTO, EXTRA_BAJO)

MODOS = ("anclado", "elasticidades")
BASES = ("pesimista", "base", "optimista")


def _paso(extra, dec, dem=None, el=None):
    fin, st0, comp = motor(float(extra))
    return fin.step(st0, dec, T.Macro(), el_medio() if el is None else el, 1, dem_override=dem) + (comp,)


def _norm_modo(m):
    return "anclado" if m == "presupuesto" else m


def razon_demanda(rep_adj: dict, rep_plan: dict, el) -> np.ndarray:
    """Cociente demanda(ajustado)/demanda(plan) según elasticidades `el` (n,3,4) o (3,4). Marca, valor y cobertura salen de cada corrida."""
    el = np.asarray(el, float)
    pa, pp_ = np.asarray(rep_adj["precio"]), np.asarray(rep_plan["precio"])
    ba, bp = np.asarray(rep_adj["marca"]), np.asarray(rep_plan["marca"])
    va, vp = np.asarray(rep_adj["valor_producto"]), np.asarray(rep_plan["valor_producto"])
    ca, cp = float(rep_adj["cobertura"]), float(rep_plan["cobertura"])
    return ((pa / pp_) ** el[..., 0]) * ((ba / bp) ** el[..., 1]) * ((va / vp) ** el[..., 2]) * ((ca / cp) ** el[..., 3])


def demanda_anclada(plan, base, rep_adj, rep_plan, el=None):
    b = np.array(plan["presupuesto_demanda"][base], float)
    return b * razon_demanda(rep_adj, rep_plan, el_medio() if el is None else el)


def correr_det(plan, ajustes, modo="anclado", base="base", extra=EXTRA_ALTO):
    """(rep_plan, new_plan, rep_adj, new_adj, advertencias, decisiones_efectivas)."""
    modo = _norm_modo(modo)
    if modo not in MODOS: raise ValueError(f"modo debe ser uno de {MODOS}")
    if base not in plan["presupuesto_demanda"]: raise ValueError(f"base debe ser una de {BASES}")
    d_eff, warns = sanear(plan, ajustes)
    dec_p, dec_a = decisions_from_plan(plan, None), decisions_from_plan(plan, ajustes)
    np_, rp0 = _paso(extra, dec_p)[:2]; na_, ra0 = _paso(extra, dec_a)[:2]
    if modo == "elasticidades": return rp0, np_, ra0, na_, warns, d_eff
    b = np.array(plan["presupuesto_demanda"][base], float)
    nP, rP = _paso(extra, dec_p, dem=b)[:2]
    nA, rA = _paso(extra, dec_a, dem=b * razon_demanda(ra0, rp0, el_medio()))[:2]
    return rP, nP, rA, nA, warns, d_eff


def informe(rep: dict, new, comp, dec: T.Decisions, score: float) -> dict:
    r = lambda k: float(rep[k])
    dot = r("margen") - (r("gasto_marketing") + r("gasto_personal") + r("gasto_id") + r("gasto_generales") + r("gasto_depreciacion")) - r("resultado_bruto")
    extr = comp.extraordinary[0]
    pyg = [("ingresos", "Ingresos", r("ingresos"), 0), ("coste_fabricacion", "Coste de fabricación", r("coste_fabricacion"), 0),
           ("coste_logistica", "Logística externa", r("coste_logistica"), 0), ("coste_no_calidad", "Coste de no calidad", r("coste_no_calidad"), 0),
           ("margen", "Margen", r("margen"), 1), ("gasto_marketing", "Marketing", r("gasto_marketing"), 0), ("gasto_personal", "Personal", r("gasto_personal"), 0),
           ("gasto_id", "I+D", r("gasto_id"), 0), ("gasto_generales", "Generales", r("gasto_generales"), 0), ("gasto_depreciacion", "Depreciación", r("gasto_depreciacion"), 0),
           ("dotaciones", "Dotaciones por insolvencias", dot, 0), ("resultado_bruto", "Resultado bruto", r("resultado_bruto"), 1),
           ("gasto_intereses", "Gastos por intereses", r("gasto_intereses"), 0), ("ingresos_financieros", "Ingresos financieros", r("ingresos_financieros"), 0),
           ("extraordinarios", "Resultados extraordinarios", float(extr), 0), ("impuestos", "Impuestos", r("impuestos"), 0), ("resultado_neto", "Resultado neto", r("resultado_neto"), 2)]
    af_net = r("activo_fijo_bruto") - r("dep_acumulada")
    tax_pay = float(new.tax_payable)
    act = af_net + comp.participations + r("af_cp") + r("af_lp") + r("inventario") + r("clientes") + r("efectivo")
    bal = [("activo_fijo_bruto", "Activo fijo bruto", r("activo_fijo_bruto"), 0), ("dep_acumulada", "Depreciación acumulada", r("dep_acumulada"), 0),
           ("af_lp", "Activos financieros LP", r("af_lp"), 0), ("af_cp", "Activos financieros CP", r("af_cp"), 0), ("clientes", "Clientes", r("clientes"), 0),
           ("efectivo", "Efectivo", r("efectivo"), 0), ("inventario", "Inventario", r("inventario"), 0), ("activo_total", "Activo total", act, 1),
           ("proveedores", "Proveedores", r("proveedores"), 0), ("prestamos_cp", "Préstamos CP", r("prestamos_cp"), 0), ("prestamos_lp", "Préstamos LP", r("prestamos_lp"), 0),
           ("credito_extraordinario", "Crédito extraordinario", r("credito_extraordinario"), 0), ("impuesto_pagar", "Impuesto por pagar", tax_pay, 0),
           ("recursos_propios", "Patrimonio contable", r("recursos_propios"), 1)]
    ing = max(r("ingresos"), 1.0)
    kpi = dict(neto=r("resultado_neto"), ingresos=r("ingresos"), margen_neto=r("resultado_neto") / ing, roe=r("roe_plataforma"), roa=r("resultado_neto") / max(act, 1.0),
               patrimonio=r("recursos_propios") + T.EQ_OFFSET, efectivo=r("efectivo"), inventario=r("inventario"), liquidez=r("liquidez"),
               deuda_patrimonio=r("deuda_patrimonio"), ocupacion=r("ocupacion_planta"), cuota=r("cuota"), indice_valor=100.0 * score,
               cobertura=r("cobertura"), capex=r("capex"), credito_extra=r("credito_extraordinario"), unidades=float(np.sum(rep["unidades_vendidas"])),
               ebit=r("resultado_bruto"))
    prods = []
    for i in range(P):
        prods.append(dict(nombre=NOMBRES[i], precio=float(rep["precio"][i]), demanda=float(rep["intencion"][i]), ventas=float(rep["unidades_vendidas"][i]),
                          produccion=float(rep["unidades"][i]), capacidad=float(new.capacity[i]), ocupacion=float(rep["ocupacion"][i]), inventario_u=float(new.inv_units[i]),
                          marca=float(rep["marca"][i]), valor=float(rep["valor_producto"][i]), cuf=float(rep["cuf"][i])))
    return dict(pyg=[dict(k=a, n=b, v=c, t=t) for a, b, c, t in pyg], balance=[dict(k=a, n=b, v=c, t=t) for a, b, c, t in bal], kpi=kpi, productos=prods,
                cuadre=float(rep["balance_error"]))


def simular(plan=None, ajustes=None, modo="anclado", base="base", extra=EXTRA_ALTO) -> dict:
    plan = plan or load_plan(); extra = float(extra)
    if extra not in (EXTRA_ALTO, EXTRA_BAJO): extra = EXTRA_ALTO
    rP, nP, rA, nA, warns, d_eff = correr_det(plan, ajustes, modo, base, extra)
    comp = motor(extra)[2]; vm = T.ValueModel(comp)
    decP, decA = decisions_from_plan(plan, None), decisions_from_plan(plan, ajustes)
    return dict(modo=_norm_modo(modo), base=base, extra=extra, advertencias=warns, decisiones=d_eff, plan_decisiones=sanear(plan, None)[0],
                capacidad=[float(x) for x in capacidad(d_eff["nivel_capacidad"])],
                plan=informe(rP, nP, comp, decP, vm.score(rP)), ajustado=informe(rA, nA, comp, decA, vm.score(rA)),
                cambios=sum(1 for k, v in (ajustes or {}).items() if v != plan["decisiones"].get(k)))
