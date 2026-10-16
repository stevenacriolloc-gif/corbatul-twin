# -*- coding: utf-8 -*-
"""Datos del panel por etapas: región factible de elasticidades (calibración) y curvas demanda-precio (modelo)."""
from __future__ import annotations
from functools import lru_cache
import numpy as np
from .montecarlo import region_factible
from . import simulador as SIM
from .plan import load_plan

PASOS = (-15, -10, -5, 0, 5, 10, 15)


@lru_cache(maxsize=1)
def region_resumen():
    """Muestras factibles y percentiles 5/50/95 de las elasticidades (precio, marca, valor, cobertura) por producto."""
    return [{"n": int(len(S)), "p": [[float(np.percentile(S[:, k], q)) for q in (5, 50, 95)] for k in range(4)]}
            for S in region_factible()]


def curvas(plan=None, ajustes=None, modo="anclado", base="base", extra=SIM.EXTRA_ALTO):
    """Demanda, ventas y neto de cada producto al mover su precio ±15 % desde las decisiones actuales (plan + ajustes)."""
    plan = plan or load_plan(); ajustes = dict(ajustes or {})
    ref = SIM.simular(plan, ajustes, modo, base, extra)
    p0 = list(ref["decisiones"]["precio"]); out = []
    for i in range(len(p0)):
        fila = []
        for s in PASOS:
            p = list(p0); p[i] = p0[i] * (1 + s / 100)
            r = SIM.simular(plan, {**ajustes, "precio": p}, modo, base, extra)
            pi = r["ajustado"]["productos"][i]
            fila.append({"s": s, "d": pi["demanda"], "v": pi["ventas"], "neto": r["ajustado"]["kpi"]["neto"]})
        out.append(fila)
    return {"region": region_resumen(), "curvas": out, "p0": p0}
