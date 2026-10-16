# -*- coding: utf-8 -*-
"""Plan de decisiones (JSON) -> objetos del gemelo, con validación de los límites del simulador."""
from __future__ import annotations
import json, math
from functools import lru_cache
from pathlib import Path
import numpy as np
from . import twin as T

DEFAULT_PLAN = Path(__file__).resolve().parent.parent / "data" / "plan_r1.json"
P = 3
NOMBRES = ("Corbatas", "Bufandas", "Calcetines")
EXTRA_ALTO, EXTRA_BAJO = 408_000.0, 138_000.0

# Límites del simulador (capturas de pantalla R1)
LISTAS = {  # clave: (min, max por producto o único, entero?)
    "precio": None, "promocion": (0, 400_000, False), "produccion": None, "gama": None,
    "diseno_up": (0, 1, True), "calidad_up": (0, 2, True), "nivel_capacidad": (0, 3, True),
}
ESCALARES = {  # clave: (min, max)
    "mantenimiento_pct": (0.01, 0.07), "descuento_canal": (0.07, 0.25), "incentivo_ventas": (0.0, 0.12),
    "dso": (1, 365), "dpo": (1, 365), "nuevo_prestamo_lp": (0, 10_000_000), "nuevo_prestamo_cp": (0, 500_000),
    "inv_fin_cp": (0, 500_000), "inv_fin_lp": (0, 1_200_000), "dividendo_pct": (0, 1),
}
PROYECTOS_R1 = ("proceso_productivo", "eficiencia_energetica")      # los demás: importe/efecto no visible -> no se adoptan
CLAVES = set(LISTAS) | set(ESCALARES) | {"proyectos"}
GAMA_MAX = (25, 15, 10)


PRECIO_RANGO = ((5.0, 35.0), (10.0, 60.0), (1.0, 10.0))   # [SUPUESTO] precio absoluto por producto; sin tope de variación entre rondas


def load_plan(path=None) -> dict:
    with open(path or DEFAULT_PLAN, encoding="utf-8") as f:
        return json.load(f)


def capacidad(nivel) -> np.ndarray:
    """Capacidad resultante por producto = capacidad del Año 0 + ampliación del nivel elegido."""
    pp = T.year0_products()
    return np.array([pp[i].cap0 + T.EXPANSION[i][int(nivel[i])][0] for i in range(P)], float)


def _num(v, nombre):
    try: x = float(v)
    except (TypeError, ValueError): raise ValueError(f"'{nombre}': valor no numérico")
    if not math.isfinite(x): raise ValueError(f"'{nombre}': valor no finito")
    return x


def sanear(plan: dict, ajustes: dict | None = None):
    """Mezcla plan + ajustes, valida y limita a los rangos del simulador. Devuelve (decisiones, advertencias)."""
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in plan["decisiones"].items()}
    w = []
    for k, v in (ajustes or {}).items():
        if k not in CLAVES: raise ValueError(f"campo desconocido: '{k}'")
        d[k] = v
    pp = T.year0_products()
    for k, lim in LISTAS.items():
        v = d[k]
        if not isinstance(v, (list, tuple)) or len(v) != 3: raise ValueError(f"'{k}' necesita 3 valores")
        v = [_num(x, k) for x in v]
        if lim:
            lo, hi, ent = lim
            for i in range(P):
                x = min(max(v[i], lo), hi); x = round(x) if ent else x
                if x != v[i]: w.append(f"{NOMBRES[i]}: '{k}' limitado a {x:g} (rango {lo:g}–{hi:g})")
                v[i] = x
        d[k] = v
    for i in range(P):
        g = min(max(d["gama"][i], 1), GAMA_MAX[i])
        if g != d["gama"][i]: w.append(f"{NOMBRES[i]}: gama limitada a {g:g} (rango 1–{GAMA_MAX[i]})")
        d["gama"][i] = g
        if d["precio"][i] <= 0: raise ValueError("el precio debe ser > 0")
        lo_p, hi_p = PRECIO_RANGO[i]; p = min(max(d["precio"][i], lo_p), hi_p)     # [DATO usuario R1] el precio es absoluto (5–35), sin tope de variación
        if p != d["precio"][i]: w.append(f"{NOMBRES[i]}: precio limitado a {p:g} (rango {lo_p:g}–{hi_p:g})")
        d["precio"][i] = p
    for k, (lo, hi) in ESCALARES.items():
        x = _num(d[k], k); y = min(max(x, lo), hi)
        if y != x: w.append(f"'{k}' limitado a {y:g} (rango {lo:g}–{hi:g})")
        d[k] = y
    if d["dividendo_pct"] > 0:
        w.append("Dividendos: no operativos en R1 (el último resultado fue negativo); se ignoran"); d["dividendo_pct"] = 0.0
    pr = d.get("proyectos", [])
    if not isinstance(pr, (list, tuple)) or any(p not in PROYECTOS_R1 for p in pr):
        raise ValueError(f"'proyectos' admite solo: {', '.join(PROYECTOS_R1)}")
    d["proyectos"] = list(dict.fromkeys(pr))
    cap = capacidad(d["nivel_capacidad"])
    for i in range(P):
        if d["produccion"][i] > cap[i]:
            w.append(f"{NOMBRES[i]}: producción limitada a la capacidad ({cap[i]:,.0f})".replace(",", ".")); d["produccion"][i] = float(cap[i])
        d["produccion"][i] = max(d["produccion"][i], 0.0)
    return d, w


def decisions_from_plan(plan: dict, overrides: dict | None = None) -> T.Decisions:
    d, _ = sanear(plan, overrides)
    cap = capacidad(d["nivel_capacidad"]); prod = np.array(d["produccion"], float)
    return T.Decisions(
        price=np.array(d["precio"], float), occ=np.clip(prod / cap, 0.0, 1.0), promo=np.array(d["promocion"], float),
        gama=np.array(d["gama"], float), design_up=np.array(d["diseno_up"], float),
        maint_pct=d["mantenimiento_pct"], channel_discount=d["descuento_canal"], sales_incentive=d["incentivo_ventas"],
        dso=d["dso"], dpo=d["dpo"], new_lp=d["nuevo_prestamo_lp"], new_cp=d["nuevo_prestamo_cp"],
        fa_cp=d["inv_fin_cp"], fa_lp=d["inv_fin_lp"], dividend_pct=d["dividendo_pct"],
        quality=np.array(d["calidad_up"], float), cap_level=np.array(d["nivel_capacidad"], float), projects=tuple(d["proyectos"]))


def build_engine(extraordinary_r1: float):
    comp = T.Company(extraordinary=(float(extraordinary_r1), float(extraordinary_r1), 18000.0, 18000.0))
    pp = T.year0_products(); st0 = T.initial_state(pp, comp)
    fin = T.Financials(pp, comp, T.MarketDemand(pp, comp), T.ProductionCosts(pp, comp))
    return fin, st0, comp


@lru_cache(maxsize=4)
def motor(extra: float):
    return build_engine(extra)


@lru_cache(maxsize=1)
def el_medio():
    """Elasticidades 'medianas' (percentil 50 de |e_precio| de la región factible)."""
    return T.demand_scenarios(3)[1]
