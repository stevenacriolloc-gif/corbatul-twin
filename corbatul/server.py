# -*- coding: utf-8 -*-
"""
Servidor local (solo biblioteca estándar + el gemelo) que sirve la app web y transmite el Monte Carlo en tiempo real.

    python -m corbatul.server                 # http://127.0.0.1:8765
    python -m corbatul.server --port 9000 --host 0.0.0.0

Endpoints
    GET /                      app web (web/index.html)
    GET /api/health            {"ok": true, ...}
    GET /api/plan              plan de la ronda + corridas de referencia (base/pesimista/optimista)
    GET /api/panel?...         Datos del panel: región factible y curvas demanda-precio con los ajustes
    GET /api/real?ronda=1      Resultados reales de la ronda + comparación gemelo vs real + ranking
    GET /api/simular?...       Simulación determinista del plan ajustado + comparación con el plan (instantánea)
        ajustes={json}  modo=anclado|elasticidades  base=pesimista|base|optimista  extra=408000|138000
    GET /api/montecarlo?...    Server-Sent Events: 'inicio' -> N x 'lote' -> 'fin'
        n, seed, modo, base, mkt_sigma, p_conv, p_extra_alto, batch, ajustes={json}
        (ajustes admite cualquier decisión de data/plan_r1.json; precio=a,b,c  promocion=a,b,c  produccion=a,b,c son atajos)
"""
from __future__ import annotations
import argparse, json, math, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from . import montecarlo as MC
from . import simulador as SIM
from . import panel as PANEL
from . import real as REAL
from .plan import load_plan, sanear

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_CONCURRENTES = 4
_sem = threading.BoundedSemaphore(MAX_CONCURRENTES)


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if math.isfinite(v) else None
    if hasattr(v, "item"): return _num(v.item())
    raise TypeError(type(v))


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=_num, allow_nan=False)


def _lista3(txt, nombre):
    v = [float(x) for x in txt.split(",")]
    if len(v) != 3 or not all(math.isfinite(x) and x >= 0 for x in v): raise ValueError(f"'{nombre}' necesita 3 números ≥ 0")
    return v


def ajustes_desde_query(q: dict) -> dict:
    """`ajustes` = JSON con cualquier decisión del plan (ver data/plan_r1.json); precio/promocion/produccion=a,b,c son atajos."""
    d = {k: v[0] for k, v in q.items()}; ov = {}
    if d.get("ajustes"):
        if len(d["ajustes"]) > 4000: raise ValueError("'ajustes' demasiado largo")
        try: ov = json.loads(d["ajustes"])
        except json.JSONDecodeError: raise ValueError("'ajustes' no es JSON válido")
        if not isinstance(ov, dict): raise ValueError("'ajustes' debe ser un objeto JSON")
    for k in ("precio", "promocion", "produccion"):
        if d.get(k): ov[k] = _lista3(d[k], k)
    sanear(load_plan(), ov)            # valida antes de abrir el stream (ValueError -> 400)
    return ov


def cfg_desde_query(q: dict) -> MC.MCConfig:
    d = {k: v[0] for k, v in q.items()}
    campos = {k: d[k] for k in ("n", "seed", "modo", "base", "mkt_sigma", "p_conv", "p_extra_alto", "batch") if k in d}
    for k in ("n", "seed", "batch"):
        if k in campos: campos[k] = int(float(campos[k]))
    for k in ("mkt_sigma", "p_conv", "p_extra_alto"):
        if k in campos: campos[k] = float(campos[k])
    campos["overrides"] = ajustes_desde_query(q)
    return MC.MCConfig.from_dict(campos)


def simular_desde_query(q: dict) -> dict:
    d = {k: v[0] for k, v in q.items()}
    modo = d.get("modo", "anclado"); base = d.get("base", "base")
    if modo not in SIM.MODOS + ("presupuesto",): raise ValueError("modo no válido")
    if base not in SIM.BASES: raise ValueError("base no válida")
    return SIM.simular(load_plan(), ajustes_desde_query(q), modo, base, float(d.get("extra", 408000)))


def panel_desde_query(q: dict) -> dict:
    d = {k: v[0] for k, v in q.items()}
    modo = d.get("modo", "anclado"); base = d.get("base", "base")
    if modo not in SIM.MODOS + ("presupuesto",): raise ValueError("modo no válido")
    if base not in SIM.BASES: raise ValueError("base no válida")
    return PANEL.curvas(load_plan(), ajustes_desde_query(q), modo, base, float(d.get("extra", 408000)))


class Handler(BaseHTTPRequestHandler):
    server_version = "CorbatulTwin/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        if "--quiet" not in sys.argv: sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % a))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = dumps(obj).encode("utf-8")
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.send_header("Content-Length", "0"); self.end_headers()

    def do_GET(self):
        u = urlparse(self.path); ruta = u.path
        try:
            if ruta in ("/", "/index.html"): return self._estatico("index.html")
            if ruta == "/api/health": return self._json(dict(ok=True, servicio="corbatul-twin", version=1))
            if ruta == "/api/plan":
                plan = load_plan(); return self._json(dict(plan=plan, referencia=MC.referencia(plan)))
            if ruta == "/api/simular": return self._json(simular_desde_query(parse_qs(u.query)))
            if ruta == "/api/real":
                rd = int(parse_qs(u.query).get("ronda", ["1"])[0]); real = REAL.load_real(rd)
                return self._json(dict(real=real, comparacion=REAL.comparar(real)))
            if ruta == "/api/panel": return self._json(panel_desde_query(parse_qs(u.query)))
            if ruta == "/api/montecarlo": return self._sse(parse_qs(u.query))
            if ruta.startswith("/web/"): return self._estatico(ruta[5:])
            self._json(dict(error="no encontrado"), 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except ValueError as e:
            self._json(dict(error=str(e)), 400)
        except Exception as e:      # noqa
            try: self._json(dict(error=f"{type(e).__name__}: {e}"), 500)
            except Exception: pass

    def _estatico(self, nombre):
        f = (WEB / nombre).resolve()
        if WEB.resolve() not in f.parents or not f.is_file(): return self._json(dict(error="no encontrado"), 404)
        tipos = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json"}
        body = f.read_bytes()
        self.send_response(200); self._cors()
        self.send_header("Content-Type", tipos.get(f.suffix, "application/octet-stream")); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache"); self.end_headers(); self.wfile.write(body)

    def _sse(self, q):
        cfg = cfg_desde_query(q)             # puede lanzar ValueError -> 400 antes de abrir el stream
        if not _sem.acquire(blocking=False): return self._json(dict(error="demasiadas simulaciones en curso"), 429)
        try:
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8"); self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no"); self.send_header("Connection", "close"); self.end_headers()
            self.close_connection = True
            for ev in MC.stream(cfg):
                self.wfile.write(f"event: {ev['tipo']}\ndata: {dumps(ev)}\n\n".encode("utf-8")); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass                            # el navegador cerró/paró la simulación
        finally:
            _sem.release()


def crear_servidor(host="127.0.0.1", port=8765) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler); srv.daemon_threads = True; return srv


def main():
    ap = argparse.ArgumentParser(description="Servidor Monte Carlo · Corbatul Twin")
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    MC.calentar()
    srv = crear_servidor(a.host, a.port)
    print(f"Corbatul Twin · Monte Carlo  ->  http://{a.host}:{a.port}   (Ctrl+C para salir)")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nCerrado.")


if __name__ == "__main__":
    main()
