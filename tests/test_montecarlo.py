import json, threading, unittest, urllib.request, urllib.error
import numpy as np
from corbatul import montecarlo as MC
from corbatul.plan import load_plan, decisions_from_plan, build_engine
from corbatul import twin as T
from corbatul import simulador as SIM
from corbatul.plan import sanear, capacidad


class TestGemelo(unittest.TestCase):
    def test_plan_r1_balance_cuadra_y_neto_de_referencia(self):
        fin, st0, _ = build_engine(MC.EXTRA_ALTO)
        plan = load_plan(); dec = decisions_from_plan(plan)
        _, rep = fin.step(st0, dec, T.Macro(), T.demand_scenarios(3)[1], 1, dem_override=plan["presupuesto_demanda"]["base"])
        self.assertAlmostEqual(rep["balance_error"], 0.0, places=2)
        self.assertAlmostEqual(rep["resultado_neto"], 830_589, delta=5)
        self.assertEqual(round(rep["ingresos"]), 4_652_054)


class TestMonteCarlo(unittest.TestCase):
    def test_reproducible_y_sin_dependencia_del_tamano_de_lote(self):
        a = MC.correr(MC.MCConfig(n=200, seed=3, batch=10)); b = MC.correr(MC.MCConfig(n=200, seed=3, batch=100))
        self.assertEqual(a["stats"]["neto"], b["stats"]["neto"])
        c = MC.correr(MC.MCConfig(n=200, seed=4, batch=50))
        self.assertNotEqual(a["stats"]["neto"]["media"], c["stats"]["neto"]["media"])

    def test_percentiles_y_probabilidades(self):
        r = MC.correr(MC.MCConfig(n=300, seed=1, batch=100))
        s = r["stats"]["neto"]
        self.assertTrue(s["min"] <= s["p5"] <= s["p25"] <= s["p50"] <= s["p75"] <= s["p95"] <= s["max"])
        for v in r["prob"].values(): self.assertTrue(0.0 <= v <= 1.0)
        self.assertEqual(sum(r["hist"]["cuenta"]), 300)

    def test_modos_y_what_if(self):
        base = MC.correr(MC.MCConfig(n=150, seed=2, modo="presupuesto", p_conv=0, mkt_sigma=0, p_extra_alto=1))
        # sin incertidumbre, el modo presupuesto reproduce la corrida determinista (la demanda ya es la del presupuesto)
        ref = base["inicio"]["referencia"]["base"]["neto"]
        self.assertAlmostEqual(base["stats"]["neto"]["media"], ref, delta=3_000)   # ruido por producto residual (mkt_sigma/2 = 0)
        menos = MC.correr(MC.MCConfig(n=150, seed=2, overrides={"produccion": [235000, 31000, 32000]}))
        self.assertNotEqual(menos["stats"]["inventario"]["media"], MC.correr(MC.MCConfig(n=150, seed=2))["stats"]["inventario"]["media"])

    def test_precio_absoluto_sin_tope(self):
        ev = next(MC.stream(MC.MCConfig(n=10, overrides={"precio": [25, 30.2, 3.04]})))
        self.assertFalse(any("Corbatas" in w for w in ev["advertencias"]))      # 25 es válido: no hay tope de ±15 %
        ev = next(MC.stream(MC.MCConfig(n=10, overrides={"precio": [40, 30.2, 3.04]})))
        self.assertTrue(any("Corbatas" in w for w in ev["advertencias"]))       # fuera del rango absoluto 5–35

    def test_config_se_sanea(self):
        c = MC.MCConfig.from_dict({"n": 10**9, "p_conv": 7, "mkt_sigma": -1})
        self.assertEqual((c.n, c.modo, c.p_conv, c.mkt_sigma), (100_000, "anclado", 1.0, 0.0))
        with self.assertRaises(ValueError): MC.MCConfig.from_dict({"modo": "raro"})
        self.assertEqual(MC.MCConfig(modo="presupuesto").modo, "anclado")


class TestSimulador(unittest.TestCase):
    def test_sin_ajustes_reproduce_el_presupuesto(self):
        r = SIM.simular()
        self.assertAlmostEqual(r["ajustado"]["kpi"]["neto"], 830_589, delta=5)
        self.assertEqual(r["plan"]["kpi"]["neto"], r["ajustado"]["kpi"]["neto"]); self.assertEqual(r["cambios"], 0)
        self.assertAlmostEqual(r["ajustado"]["cuadre"], 0.0, places=2)

    def test_ajustes_mueven_resultados_y_cuadran(self):
        r = SIM.simular(ajustes={"precio": [17.5, 30.2, 3.04], "nivel_capacidad": [2, 1, 0], "proyectos": ["proceso_productivo"], "inv_fin_lp": 500000})
        self.assertNotEqual(r["ajustado"]["kpi"]["neto"], r["plan"]["kpi"]["neto"]); self.assertEqual(r["capacidad"][0], 255_000)
        self.assertAlmostEqual(r["ajustado"]["cuadre"], 0.0, places=2); self.assertEqual(r["cambios"], 4)

    def test_validacion_y_limites(self):
        plan = load_plan()
        with self.assertRaises(ValueError): sanear(plan, {"campo_raro": 1})
        with self.assertRaises(ValueError): sanear(plan, {"proyectos": ["esg_r1"]})
        with self.assertRaises(ValueError): sanear(plan, {"precio": [1, 2]})
        d, w = sanear(plan, {"produccion": [300000, 36000, 32000], "dividendo_pct": 0.3, "mantenimiento_pct": 0.5})
        self.assertEqual(d["produccion"][0], 235_000); self.assertEqual(d["dividendo_pct"], 0.0); self.assertEqual(d["mantenimiento_pct"], 0.07)
        self.assertTrue(len(w) >= 3)
        self.assertEqual(list(capacidad([1, 1, 0])), [235_000, 38_000, 40_000])

    def test_modo_elasticidades_difiere_del_anclado(self):
        a = SIM.simular(modo="anclado")["plan"]["kpi"]["neto"]; e = SIM.simular(modo="elasticidades")["plan"]["kpi"]["neto"]
        self.assertNotAlmostEqual(a, e, delta=1000)


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from corbatul.server import crear_servidor
        cls.srv = crear_servidor("127.0.0.1", 0); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def get(self, ruta):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{ruta}", timeout=60)

    def test_health_y_cors(self):
        r = self.get("/api/health"); self.assertEqual(json.load(r)["ok"], True)
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "*")

    def test_sse(self):
        r = self.get("/api/montecarlo?n=60&batch=20&seed=5")
        self.assertIn("text/event-stream", r.headers["Content-Type"])
        eventos = [b.split("\n")[0][7:] for b in r.read().decode().split("\n\n") if b.strip()]
        self.assertEqual(eventos[0], "inicio"); self.assertEqual(eventos[-1], "fin"); self.assertEqual(eventos.count("lote"), 3)

    def test_api_simular(self):
        import urllib.parse
        q = urllib.parse.quote(json.dumps({"precio": [17.5, 30.2, 3.04]}))
        j = json.load(self.get("/api/simular?ajustes=" + q)); self.assertEqual(j["cambios"], 1)
        self.assertLess(j["ajustado"]["kpi"]["neto"], j["plan"]["kpi"]["neto"])
        with self.assertRaises(urllib.error.HTTPError) as cm: self.get("/api/simular?ajustes=" + urllib.parse.quote('{"x":1}'))
        self.assertEqual(cm.exception.code, 400)
        r = self.get("/api/montecarlo?n=30&batch=30&ajustes=" + q).read().decode(); self.assertIn("event: lote", r)

    def test_parametros_invalidos(self):
        with self.assertRaises(urllib.error.HTTPError) as cm: self.get("/api/montecarlo?precio=1,2")
        self.assertEqual(cm.exception.code, 400)

    def test_index_y_sin_path_traversal(self):
        self.assertIn(b"Monte Carlo", self.get("/").read())
        for ruta in ("/web/../corbatul/twin.py", "/web/..%2fcorbatul%2ftwin.py"):
            with self.assertRaises(urllib.error.HTTPError) as cm: self.get(ruta)
            self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()


class TestPanel(unittest.TestCase):
    def test_panel_curvas_y_region(self):
        from corbatul.server import panel_desde_query
        r = panel_desde_query({"ajustes": ['{"precio":[17.4,30.2,3.04]}']})
        self.assertEqual(len(r["region"]), 3)
        self.assertEqual([len(f) for f in r["curvas"]], [7, 7, 7])
        self.assertAlmostEqual(r["p0"][0], 17.4)
        d = [x["d"] for x in r["curvas"][0]]
        self.assertTrue(all(a >= b for a, b in zip(d, d[1:])))   # demanda decreciente con el precio
        with self.assertRaises(ValueError):
            panel_desde_query({"modo": ["xx"]})


class TestPresupuesto(unittest.TestCase):
    def test_puente_de_caja_cuadra(self):
        from corbatul.presupuesto import desviaciones
        x = desviaciones()
        self.assertAlmostEqual(sum(v for _, v in x["puente_caja"]), x["desv_caja"], delta=2)


class TestR2(unittest.TestCase):
    def test_balance_cuadra_y_ingresos_backtest(self):
        import numpy as np
        from corbatul.r2 import PlanR2, simular
        r = simular(PlanR2(nuevo_lp=0), np.full(3, 1e9))
        self.assertLess(abs(r["cuadre"]), 1.0)
        g = simular(PlanR2(precio=[19.9, 30.4, 3.5], nivel_ampliacion=[1, 0, 0], produccion_pct=[1, 1, 0.7], nuevo_lp=0), np.full(3, 1e9))
        self.assertAlmostEqual(dict(g["pyg"])["Ingresos totales"] / 5369937, 1.0, delta=0.002)   # R2 real del ganador
        self.assertAlmostEqual(dict(g["pyg"])["Gastos de personal"] / 745775, 1.0, delta=0.002)
