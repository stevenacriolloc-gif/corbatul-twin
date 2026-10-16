# -*- coding: utf-8 -*-
"""
Simulación Monte Carlo del plan de una ronda sobre el gemelo digital CORBATUL.

Qué es incierto (y se muestrea en cada simulación)
  1. Elasticidades de demanda  -> filas tomadas al azar de la REGIÓN FACTIBLE (consistente con lo que vendió el 2º lugar).
  2. Tamaño de mercado         -> multiplicador lognormal común (σ=mkt_sigma) + ruido propio por producto (σ=mkt_sigma/2).
  3. Conversión intención→venta-> con prob. p_conv vale ~0,865 (observado en el Año 0), si no 1,0.        [SUPUESTO]
  4. Ingreso extraordinario R1 -> 408.000 (prob. p_extra_alto) o 138.000.                                  [SUPUESTO]
Modo "presupuesto": en vez de elasticidades, la demanda es la del presupuesto base × (mercado, conversión).

Todo se sortea de antemano con una semilla -> mismos resultados con la misma semilla, sin importar el tamaño de lote.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
import numpy as np
from . import twin as T
from .plan import load_plan, decisions_from_plan, sanear, motor, el_medio, EXTRA_ALTO, EXTRA_BAJO, NOMBRES, P
from . import simulador as SIM

MODOS = ("anclado", "elasticidades")

# métricas guardadas por simulación (clave -> etiqueta)
METRICAS = {
    "neto": "Resultado neto", "ingresos": "Ingresos", "bruto": "Resultado bruto (EBIT)", "margen": "Margen",
    "caja": "Efectivo", "inventario": "Inventario", "credito_extra": "Crédito extraordinario",
    "roe": "ROE (plataforma)", "liquidez": "Liquidez", "score": "Proxy valor compañía",
    "uds_corbatas": "Uds. corbatas", "uds_bufandas": "Uds. bufandas", "uds_calcetines": "Uds. calcetines", "uds_total": "Uds. totales",
    "intencion_corbatas": "Demanda corbatas", "intencion_bufandas": "Demanda bufandas", "intencion_calcetines": "Demanda calcetines",
    "ocupacion": "Ocupación planta", "cuota": "Cuota de mercado",
}
ENTRADAS = ("mkt", "conv", "extra_alto", "ep_corb", "ep_buf", "ep_calc", "ec_corb", "ev_corb")
ETIQ_ENTRADAS = {
    "mkt": "Tamaño de mercado", "conv": "Conversión de ventas", "extra_alto": "Extraordinarios 408 k",
    "ep_corb": "Elasticidad precio corbatas", "ep_buf": "Elasticidad precio bufandas", "ep_calc": "Elasticidad precio calcetines",
    "ec_corb": "Elast. cobertura corbatas", "ev_corb": "Elast. valor corbatas",
}


@dataclass
class MCConfig:
    n: int = 5000
    seed: int = 42
    modo: str = "anclado"
    base: str = "base"            # escenario del presupuesto que ancla la demanda: pesimista | base | optimista
    mkt_sigma: float = 0.06       # σ lognormal del mercado
    p_conv: float = 0.20          # prob. de que se repita la conversión 0,865
    conv_valor: float = 0.865
    conv_sd: float = 0.03
    p_extra_alto: float = 0.70
    batch: int = 25
    umbral_inv: float = 150_000.0     # "inventario alto"
    umbral_caja: float = 500_000.0    # "caja baja"
    overrides: dict = field(default_factory=dict)   # cambios al plan: precio, promocion, produccion, ...

    def __post_init__(self):
        if self.modo == "presupuesto": self.modo = "anclado"      # alias antiguo
        if self.modo not in MODOS: raise ValueError(f"modo debe ser uno de {MODOS}")
        if self.base not in ("pesimista", "base", "optimista"): raise ValueError("base no válida")

    @staticmethod
    def from_dict(d: dict) -> "MCConfig":
        base = MCConfig(); out = {}
        for k, v in (d or {}).items():
            if k in base.__dict__ and v is not None:
                out[k] = type(base.__dict__[k])(v) if not isinstance(base.__dict__[k], dict) else dict(v)
        c = MCConfig(**out)
        c.n = int(np.clip(c.n, 10, 100_000)); c.batch = int(np.clip(c.batch, 1, 2000))
        c.mkt_sigma = float(np.clip(c.mkt_sigma, 0.0, 0.5)); 
        for k in ("p_conv", "p_extra_alto"): setattr(c, k, float(np.clip(getattr(c, k), 0.0, 1.0)))
        return c


@lru_cache(maxsize=1)
def region_factible():
    out = []
    for i in range(P):
        S = T.feasible_demand_params(i)
        if len(S) < 5: S = T.feasible_demand_params(i, tol_exact=0.35, tol_lower=0.25)
        if len(S) == 0: S = np.array([[-1.5, 0.3, 0.5, 0.5]])
        out.append(S)
    return out


def _motor(extra: float):
    return motor(float(extra))


def _el_medio():
    return el_medio()


def calentar():
    """Precalcula lo costoso (región factible, motores) para que la primera simulación arranque al instante."""
    region_factible(); _el_medio(); _motor(EXTRA_ALTO); _motor(EXTRA_BAJO); presupuesto_neto()


def referencia(plan: dict | None = None, overrides: dict | None = None, modo: str = "anclado") -> dict:
    """Corridas deterministas (extraordinarios altos) con el plan ajustado y la demanda del presupuesto pesimista / base / optimista."""
    plan = plan or load_plan(); out = {}
    for nombre in plan["presupuesto_demanda"]:
        rP, nP, rA, nA, _, _ = SIM.correr_det(plan, overrides, "anclado", nombre, EXTRA_ALTO)
        out[nombre] = dict(neto=rA["resultado_neto"], ingresos=rA["ingresos"], caja=rA["efectivo"], inventario=rA["inventario"], bruto=rA["resultado_bruto"])
    return out


def presupuesto_neto(plan: dict | None = None) -> float:
    """Resultado neto del presupuesto original (plan sin ajustes, demanda base, extraordinarios altos)."""
    return float(referencia(plan, None)["base"]["neto"])


def _sortear(cfg: MCConfig, plan: dict):
    rng = np.random.default_rng(cfg.seed); n = cfg.n
    regs = region_factible()
    idx = [rng.integers(0, len(regs[i]), n) for i in range(P)]
    el = np.stack([regs[i][idx[i]] for i in range(P)], axis=1)                    # (n, 3, 4)
    mk = np.exp(rng.normal(0, cfg.mkt_sigma, n))
    mk_i = mk[:, None] * np.exp(rng.normal(0, cfg.mkt_sigma / 2, (n, P)))        # (n, 3)
    conv = np.where(rng.random(n) < cfg.p_conv, np.clip(rng.normal(cfg.conv_valor, cfg.conv_sd, n), 0.7, 1.0), 1.0)
    extra = rng.random(n) < cfg.p_extra_alto
    return el, mk, mk_i, conv, extra


def _stats(x: np.ndarray) -> dict:
    p = np.percentile(x, [5, 25, 50, 75, 95])
    return dict(media=float(x.mean()), sd=float(x.std()), min=float(x.min()), max=float(x.max()),
                p5=float(p[0]), p25=float(p[1]), p50=float(p[2]), p75=float(p[3]), p95=float(p[4]))


def _rangos(x):
    r = np.argsort(np.argsort(x)); return r.astype(float)


def sensibilidad(inp: dict, y: np.ndarray) -> list:
    """Correlación de rangos (Spearman) entre cada entrada incierta y el resultado neto."""
    out = []; ry = _rangos(y)
    for k in ENTRADAS:
        x = inp[k]
        if np.ptp(x) < 1e-12: continue
        c = float(np.corrcoef(_rangos(x), ry)[0, 1])
        if np.isfinite(c): out.append(dict(clave=k, nombre=ETIQ_ENTRADAS[k], rho=c))
    return sorted(out, key=lambda r: -abs(r["rho"]))


def stream(cfg: MCConfig, plan: dict | None = None):
    """Generador de eventos: {'tipo':'inicio'|'lote'|'fin', ...}. Cada 'lote' trae las estadísticas acumuladas."""
    plan = plan or load_plan(); dec = decisions_from_plan(plan, cfg.overrides); t0 = time.time()
    d_eff, warns = sanear(plan, cfg.overrides)
    el, mk, mk_i, conv, extra = _sortear(cfg, plan)
    base_dem = np.array(plan["presupuesto_demanda"][cfg.base], float); mac0 = T.Macro(); n = cfg.n
    ref = referencia(plan, cfg.overrides); pres = presupuesto_neto(plan)
    ratio = None
    if cfg.modo == "anclado":      # demanda = presupuesto × reacción del modelo a los ajustes (marca/valor/cobertura/precio vs plan), por muestra de elasticidades
        rP, _, rA, _, _, _ = SIM.correr_det(plan, cfg.overrides, "anclado", cfg.base, EXTRA_ALTO)
        rp0 = _motor(EXTRA_ALTO)[0].step(_motor(EXTRA_ALTO)[1], decisions_from_plan(plan, None), T.Macro(), _el_medio(), 1)[1]
        ra0 = _motor(EXTRA_ALTO)[0].step(_motor(EXTRA_ALTO)[1], dec, T.Macro(), _el_medio(), 1)[1]
        ratio = SIM.razon_demanda(ra0, rp0, el)                       # (n, 3)
    yield dict(tipo="inicio", cfg=asdict(cfg), n=n, referencia=ref, presupuesto_neto=pres, advertencias=warns,
               metricas=METRICAS, produccion=[float(v) for v in d_eff["produccion"]], precio=[float(v) for v in dec.price],
               promocion=[float(v) for v in dec.promo], decisiones=d_eff, equipo=plan.get("equipo"), ronda=plan.get("ronda"))
    M = {k: np.zeros(n) for k in METRICAS}
    inp = dict(mkt=mk, conv=conv, extra_alto=extra.astype(float), ep_corb=el[:, 0, 0], ep_buf=el[:, 1, 0], ep_calc=el[:, 2, 0],
               ec_corb=el[:, 0, 3], ev_corb=el[:, 0, 2])
    vm = T.ValueModel(_motor(EXTRA_ALTO)[2]); edges = None; k0 = 0; hist_hi = None
    while k0 < n:
        k1 = min(k0 + cfg.batch, n)
        for s in range(k0, k1):
            fin, st0, _ = _motor(EXTRA_ALTO if extra[s] else EXTRA_BAJO)
            mkt_idx = tuple(tuple(v * mk_i[s, i] for v in mac0.mkt_idx[i]) for i in range(P))
            if cfg.modo == "anclado":
                mac = T.Macro(mkt_idx=mac0.mkt_idx); dem = base_dem * ratio[s] * mk_i[s] * conv[s]
                new, rep = fin.step(st0, dec, mac, el[s], 1, dem_override=dem)
            else:
                mac = T.Macro(mkt_idx=mkt_idx, conv=float(conv[s]))
                new, rep = fin.step(st0, dec, mac, el[s], 1)
            u = np.asarray(rep["unidades_vendidas"], float); it = np.asarray(rep["intencion"], float)
            M["neto"][s] = rep["resultado_neto"]; M["ingresos"][s] = rep["ingresos"]; M["bruto"][s] = rep["resultado_bruto"]
            M["margen"][s] = rep["margen"]; M["caja"][s] = rep["efectivo"]; M["inventario"][s] = rep["inventario"]
            M["credito_extra"][s] = rep["credito_extraordinario"]; M["roe"][s] = rep["roe_plataforma"]; M["liquidez"][s] = rep["liquidez"]
            M["score"][s] = vm.score(rep); M["uds_total"][s] = u.sum()
            for i, nm in enumerate(("corbatas", "bufandas", "calcetines")): M["uds_" + nm][s] = u[i]; M["intencion_" + nm][s] = it[i]
            M["ocupacion"][s] = rep["ocupacion_planta"]; M["cuota"][s] = rep["cuota"]
        k0 = k1
        if edges is None:      # bins fijos a partir de la primera tanda (≥ 60 sims): evita que el histograma "salte"
            if k0 >= min(60, n) or k0 == n:
                lo, hi = np.percentile(M["neto"][:k0], [0.5, 99.5]); w = max(hi - lo, 1.0)
                edges = np.linspace(lo - 0.6 * w, hi + 0.6 * w, 41)
        y = M["neto"][:k0]
        ev = dict(tipo="lote", hechas=k0, n=n, t=round(time.time() - t0, 3), media_neto=float(y.mean()))
        if edges is not None:
            h = np.histogram(np.clip(y, edges[0], edges[-1] - 1e-9), bins=edges)[0]
            ev["hist"] = dict(bordes=[float(e) for e in edges], cuenta=[int(c) for c in h])
        ev["stats"] = {k: _stats(M[k][:k0]) for k in ("neto", "ingresos", "caja", "inventario", "bruto", "uds_total", "score", "roe")}
        yy = {k: M[k][:k0] for k in M}
        ev["prob"] = dict(perdida=float((y < 0).mean()), bajo_presupuesto=float((y < pres).mean()),
                          sobre_pesimista=float((y >= ref["pesimista"]["neto"]).mean()),
                          inventario_alto=float((yy["inventario"] > cfg.umbral_inv).mean()),
                          caja_baja=float((yy["caja"] < cfg.umbral_caja).mean()),
                          credito_extra=float((yy["credito_extra"] > 1).mean()),
                          neto_sobre_1m=float((y > 1_000_000).mean()))
        ev["ic95_media"] = [float(y.mean() - 1.96 * y.std() / np.sqrt(k0)), float(y.mean() + 1.96 * y.std() / np.sqrt(k0))]
        ev["productos"] = [dict(nombre=NOMBRES[i], demanda=_stats(yy["intencion_" + ("corbatas", "bufandas", "calcetines")[i]]),
                                ventas=_stats(yy["uds_" + ("corbatas", "bufandas", "calcetines")[i]]),
                                produccion=ev_prod) for i, ev_prod in enumerate(plan["decisiones"]["produccion"])]
        if k0 >= 40 and (k0 == n or (k0 // cfg.batch) % 4 == 0):
            ev["sensibilidad"] = sensibilidad({k: v[:k0] for k, v in inp.items()}, y)
        yield ev
    yield dict(tipo="fin", hechas=n, t=round(time.time() - t0, 3), sims_por_s=round(n / max(time.time() - t0, 1e-9), 1))


def correr(cfg: MCConfig | None = None, plan: dict | None = None) -> dict:
    """Ejecuta todo y devuelve el último evento 'lote' (sin streaming). Útil en scripts y tests."""
    ult = None; ini = None
    for ev in stream(cfg or MCConfig(), plan):
        if ev["tipo"] == "inicio": ini = ev
        elif ev["tipo"] == "lote": ult = ev
    ult["inicio"] = ini
    return ult


if __name__ == "__main__":
    import json, sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    r = correr(MCConfig(n=n))
    s = r["stats"]["neto"]
    print(f"{r['hechas']} simulaciones en {r['t']} s")
    print(f"Resultado neto: media {s['media']:,.0f} | P5 {s['p5']:,.0f} | P50 {s['p50']:,.0f} | P95 {s['p95']:,.0f}")
    print("Probabilidades:", json.dumps({k: round(v, 3) for k, v in r["prob"].items()}, ensure_ascii=False))
