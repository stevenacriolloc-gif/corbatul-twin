# -*- coding: utf-8 -*-
"""Revisión del presupuesto enviado frente al resultado real (puntúa Presupuestación: resultados y balance).

    python -m corbatul.presupuesto        # desviaciones R1 y puente de caja
"""
from __future__ import annotations
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# Causas identificadas en R1 y corrección para el presupuesto de R2
CAUSAS_R1 = [
    ("Resultado extraordinario", "Se presupuestó 408.000 (supuesto copiado del 2.º lugar); el real fue 18.000, el ingreso extraordinario recurrente.", "Presupuestar 18.000."),
    ("Activos financieros LP", "La decisión de 800.000 se SUMA a los 150.000 que ya había: el saldo real fue 950.000.", "Saldo = existente + compra; sube también el ingreso financiero."),
    ("Gastos generales", "+48.336 (+33 %): los procesos administrativos son ≈ 4,2 % de los ingresos (4,20 % 2024, 4,24 % 2025, 4,18 % 2026); el gemelo solo aplicaba el IPC.", "Presupuestar 4,18 % × ingresos previstos."),
    ("Proveedores", "−41.272 (−13 %): con 50 días el saldo real equivale a ~43 días de compras.", "Aplicar factor 0,866 al saldo de proveedores."),
    ("Clientes", "−17.015 (−4 %): con 40 días el saldo real equivale a ~38 días.", "Aplicar factor 0,956; la dotación (= Δclientes/3) se corrige sola."),
    ("Impuestos", "La línea «Resultado neto» del presupuesto es ANTES de impuestos. Impuesto real 15.116 = 25 % × (557.930 − 497.464 de pérdidas compensables): el gemelo tenía bien las pérdidas; se agotaron en R1.", "En R2 tributa todo el beneficio al 25 %; presupuestar el neto antes de impuestos en esa línea."),
]


def cargar(ronda: int = 1) -> dict:
    return json.loads((DATA / f"presupuesto_r{ronda}.json").read_text(encoding="utf-8"))


def desviaciones(d: dict | None = None) -> dict:
    d = d or cargar()
    def tabla(rows): return [dict(concepto=n, real=r, presupuesto=p, desv=r - p, pct=(r - p) / p if p else None) for n, r, p in rows]
    R, B = tabla(d["resultados"]), tabla(d["balance"])
    g = {x["concepto"]: x for x in B}
    puente = [("Resultado neto", g["Resultado neto"]["desv"]), ("Activos financieros LP", -g["Activos financieros LP"]["desv"]),
              ("Clientes", -g["Clientes"]["desv"]), ("Inventario", -g["Inventario"]["desv"]), ("Proveedores", g["Proveedores"]["desv"]),
              ("Préstamo LP", g["Préstamo LP"]["desv"]), ("Préstamo CP", g["Préstamo CP"]["desv"])]
    return dict(resultados=R, balance=B, puente_caja=puente, desv_caja=g["Efectivo"]["desv"], causas=CAUSAS_R1)


if __name__ == "__main__":
    x = desviaciones()
    for blk in ("resultados", "balance"):
        print(f"== {blk}")
        for f in x[blk]:
            print(f"  {f['concepto']:28s} real {f['real']:>11,}  presupuesto {f['presupuesto']:>11,}  desv {f['desv']:>+10,}" + (f"  {f['pct']*100:+6.1f} %" if f["pct"] is not None else ""))
    print(f"\nPuente de la desviación de caja ({x['desv_caja']:+,}):")
    for n, v in x["puente_caja"]: print(f"  {n:24s} {v:>+10,}")
    print("\nCausas y corrección para R2:")
    for c, por, fix in x["causas"]: print(f"  - {c}: {por} → {fix}")
