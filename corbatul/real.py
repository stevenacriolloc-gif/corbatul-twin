# -*- coding: utf-8 -*-
"""Resultados reales de cada ronda y comparación con el gemelo (pronóstico vs real).

    python -m corbatul.real            # informe de la Ronda 1
"""
from __future__ import annotations
import json
from pathlib import Path
from . import simulador as SIM
from .plan import load_plan, EXTRA_ALTO, EXTRA_BAJO

DATA = Path(__file__).resolve().parent.parent / "data"


def load_real(ronda: int = 1) -> dict:
    return json.loads((DATA / f"real_r{ronda}.json").read_text(encoding="utf-8"))


def ranking(real: dict) -> list:
    v = real["valor_compania"]["2026"]; c = real["companias"]
    return [dict(puesto=i + 1, compania=c[j], valor=v[j]) for i, j in enumerate(sorted(range(len(c)), key=lambda k: -v[k]))]


def comparar(real: dict | None = None, plan: dict | None = None) -> dict:
    """Pronóstico del gemelo para el plan enviado (extraordinarios 408 k y 138 k) frente a lo real de RealMan."""
    real = real or load_real(); plan = plan or load_plan(); r = real["realman"]["2026"]
    pred = {}
    for nombre, extra in (("alto", EXTRA_ALTO), ("bajo", EXTRA_BAJO)):
        a = SIM.simular(plan, None, "anclado", "base", extra)["ajustado"]
        k, P = a["kpi"], a["productos"]
        uds = sum(p["ventas"] for p in P)
        pred[nombre] = dict(extra=extra, ventas_u=uds, ingresos=k["ingresos"], neto=k["neto"], produccion=sum(p["produccion"] for p in P),
                            ocupacion=k["ocupacion"], cobertura=k["cobertura"],
                            margen_bruto=next((x["v"] for x in a["pyg"] if x["k"] == "margen"), 0) / k["ingresos"],
                            marca=sum(p["marca"] * p["ventas"] for p in P) / uds, valor=sum(p["valor"] * p["ventas"] for p in P) / uds,
                            inventario_u=sum(p["inventario_u"] for p in P))
    filas = [("Unidades vendidas", r["ventas_u"], "ventas_u", 1), ("Ingresos", r["ingresos_miles"] * 1e3, "ingresos", 1),
             ("Resultado neto", r["neto_miles"] * 1e3, "neto", 1), ("Unidades producidas", r["produccion_miles"] * 1e3, "produccion", 1),
             ("Ocupación de fábrica", r["ocupacion_pct"] / 100, "ocupacion", 1), ("Margen bruto / ingresos", r["margen_bruto_pct"] / 100, "margen_bruto", 1),
             ("Cobertura de distribución", r["cobertura_pct"] / 100, "cobertura", 1), ("Valor de marca", r["valor_marca"], "marca", 1),
             ("Valor de producto", r["valor_producto"], "valor", 1), ("Inventario (u)", r["inventario_miles_u"] * 1e3, "inventario_u", 1)]
    out = [dict(indicador=n, real=v, pred_alto=pred["alto"][k], pred_bajo=pred["bajo"][k],
                error_alto=(pred["alto"][k] - v) / v if v else None, error_bajo=(pred["bajo"][k] - v) / v if v else None) for n, v, k, _ in filas]
    # el neto real se explica mejor con extraordinarios bajos; el resto del desvío queda como sesgo del presupuesto
    neto_r = r["neto_miles"] * 1e3
    sesgo = dict(neto_vs_bajo=neto_r - pred["bajo"]["neto"], neto_vs_alto=neto_r - pred["alto"]["neto"],
                 extraordinario_probable="bajo" if abs(neto_r - pred["bajo"]["neto"]) < abs(neto_r - pred["alto"]["neto"]) else "alto",
                 factor_ingresos=r["ingresos_miles"] * 1e3 / pred["alto"]["ingresos"], factor_unidades=r["ventas_u"] / pred["alto"]["ventas_u"])
    return dict(filas=out, sesgo=sesgo, ranking=ranking(real), productos=comparar_productos(real, plan), costes=comparar_costes(plan))


def comparar_productos(real: dict | None = None, plan: dict | None = None) -> list:
    """Por producto: unidades implícitas (ingresos / precio neto), marca y valor de producto reales frente al gemelo."""
    real = real or load_real(); plan = plan or load_plan(); pr = real.get("productos")
    if not pr: return []
    a = SIM.simular(plan, None, "anclado", "base", EXTRA_ALTO)["ajustado"]["productos"]; rm = pr["realman"]; out = []
    for i, n in enumerate(pr["nombres"]):
        uds = rm["ingresos_producto"]["2026"][i] / rm["precio_neto_2026"][i]
        out.append(dict(producto=n, uds_real=uds, uds_gemelo=a[i]["ventas"], marca_real=rm["marca"]["2026"][i], marca_gemelo=a[i]["marca"],
                        valor_real=rm["valor_producto"]["2026"][i], valor_gemelo=a[i]["valor"], precio=rm["precio"]["2026"][i],
                        precio_sector=pr["precio_sector"]["promedio"][i]))
    return out


def comparar_costes(plan: dict | None = None) -> list:
    """Costes de fabricación de la R1 por componente: real (Cuadro de Mando) frente al gemelo, por producto."""
    from . import plan as PL
    f = DATA / "produccion_r1.json"
    if not f.exists(): return []
    real = json.loads(f.read_text(encoding="utf-8")); plan = plan or load_plan()
    fin, st0, comp = PL.motor(float(EXTRA_ALTO)); rec = []; orig = fin.pc.unit_components
    def spy(i, *a, **k):
        r = orig(i, *a, **k); rec.append((i, r)); return r
    fin.pc.unit_components = spy
    try: SIM.simular(plan, None, "anclado", "base", EXTRA_ALTO)
    finally: fin.pc.unit_components = orig
    u = {i: c for i, c in rec[-3:]}; q = real["producidas"]["2026"]; R = real["costes_fabricacion_produccion"]["2026"]
    out = []
    for comp_k, real_k in (("mp", "mp"), ("elab", "elab"), ("energy", "energia"), ("pers", "personal")):
        gem = [float(u[i][comp_k]) * q[i] for i in range(3)]
        out.append(dict(componente=real_k, real=R[real_k], gemelo=gem, factor=[R[real_k][i] / gem[i] if gem[i] else None for i in range(3)]))
    return out


if __name__ == "__main__":
    c = comparar()
    print("Ranking Valor de la Compañía R1:")
    for x in c["ranking"]: print(f"  {x['puesto']}. {x['compania']:12s} {x['valor']:8.1f}")
    print("\nGemelo vs real (RealMan):")
    for f in c["filas"]:
        print(f"  {f['indicador']:28s} real {f['real']:>14,.3f}  pred(408k) {f['pred_alto']:>14,.3f}  pred(138k) {f['pred_bajo']:>14,.3f}  err {f['error_bajo']*100:+6.1f} %")
    print("\nPor producto:")
    for p in c["productos"]:
        print(f"  {p['producto']:11s} uds {p['uds_real']:9,.0f} vs {p['uds_gemelo']:9,.0f} · marca {p['marca_real']:4.0f} vs {p['marca_gemelo']:5.1f} · valor {p['valor_real']:4.1f} vs {p['valor_gemelo']:5.2f}")
    print("\nCostes de fabricación R1 (real / gemelo):")
    for x in comparar_costes():
        print(f"  {x['componente']:10s} " + " · ".join(f"{r:,.0f}/{g:,.0f} (x{fc:.3f})" for r, g, fc in zip(x['real'], x['gemelo'], x['factor'])))
    print("\nSesgo:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in c["sesgo"].items()})
