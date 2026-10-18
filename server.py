"""Local research workbench. No accounts, cloud services or API keys."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
import hashlib
from urllib.parse import parse_qs, urlparse, unquote

from .demo import seed_demo
from .adapters import inventory
from .api_schema import openapi
from .features import extract
from .model import predict, train
from .recorder import Recorder
from .storage import Store
from .backup import WorkspaceLock, create_backup
from . import __version__
from .workspace import setup_status, run_practice, load_plan, save_plan, plan_rows, plan_csv

WEB = Path(__file__).parent / "web"


class App:
    def __init__(self, directory, registry=None, allowed_origins=()):
        self.workspace_lock = WorkspaceLock(directory)
        try:
            self.store = Store(directory)
            self.recorder = Recorder(self.store, registry=registry)
        except Exception:
            self.workspace_lock.close()
            raise
        self.allowed_origins = set(allowed_origins)
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.path or parsed.query or parsed.fragment or parsed.username:
                self.recorder.close()
                self.workspace_lock.close()
                raise ValueError("--allow-origin must be an exact local HTTP(S) origin, such as http://localhost:3000.")
        self.token = secrets.token_urlsafe(32)
        self.mutation_lock = threading.Lock()

    def close(self):
        try:
            self.recorder.close()
        finally:
            self.workspace_lock.close()

    def backup(self):
        with self.mutation_lock, self.recorder.lock:
            if self.recorder.active:
                raise ValueError("Finish or abort the current scan before making a complete backup.")
            return create_backup(self.store)

    def state(self, mode):
        scans = self.store.list(mode)
        model = self.store.load_model(mode)
        return {"api_version": 1, "schema_version": 1, "mode": mode, "csrf_token": self.token, "scans": scans,
                "catalogue_summary": self.store.catalogue.summary(),
                "saved_scan_ids": self.store.bookmarks(mode),
                "index_errors": list(self.store.index_errors),
                "groups": sorted({s["group_id"] for s in scans if s["status"] == "complete"}),
                "recorder": self.recorder.status(),
                "model": ({k: model[k] for k in ("model_id", "created_at", "classes", "train_groups",
                           "train_scan_ids", "heldout_group", "report", "limitations")} | {"signal_profile_key": model.get("signal_profile_key")} if model else None)}

    def action(self, route, data):
        versioned = route.startswith("/api/v1/")
        if versioned:
            route = "/api/" + route[len("/api/v1/"):]
        mode = data.get("mode", "simulation")
        if mode not in ("simulation", "real"):
            raise ValueError("Invalid workspace.")
        with self.mutation_lock:
            if route == "/api/practice":
                if mode != "simulation":
                    raise ValueError("Practice uses generated simulation data only.")
                if self.recorder.status()["active"]:
                    raise ValueError("Finish or abort the current recording before running practice.")
                return run_practice()
            if route == "/api/plan":
                if self.recorder.status()["active"]:
                    raise ValueError("Finish or abort the current recording before changing the experiment plan.")
                return {"plan": save_plan(self.store, {k: v for k, v in data.items() if k != "mode"})}
            if route == "/api/seed":
                if mode != "simulation":
                    raise ValueError("Synthetic examples are only available in simulation mode.")
                return seed_demo(self.store)
            if route == "/api/connect":
                if mode != "real":
                    raise ValueError("Choose real mode before connecting hardware.")
                adapter_id = data.get("adapter_id", "bme688")
                config = data.get("config", {"address": data.get("address", "auto")} if adapter_id == "bme688" else {})
                info = self.recorder.connect(adapter_id, config)
                return {"connected": True, "sensor": info}
            if route == "/api/disconnect":
                self.recorder.disconnect()
                return {"connected": False}
            if route == "/api/start":
                return {"scan_id": self.recorder.start(mode, data)}
            if route == "/api/capture":
                duration = data.get("duration_s", 10)
                if duration is None:
                    raise ValueError("Quick capture duration must be between 5 and 60 seconds.")
                return {"scan_id": self.recorder.start(mode, data, quick_duration=duration), "duration_s": duration, "capture_mode": "quick"}
            if route == "/api/phase":
                if versioned and not data.get("scan_id"):
                    raise ValueError("v1 scan commands require scan_id from /api/v1/status.")
                self.recorder.advance(mode=mode, scan_id=data.get("scan_id"))
                return {"ok": True}
            if route in ("/api/finish", "/api/abort"):
                if versioned and not data.get("scan_id"):
                    raise ValueError("v1 scan commands require scan_id from /api/v1/status.")
                return {"scan_id": self.recorder.finish(abort=route.endswith("abort"), mode=mode, scan_id=data.get("scan_id"))}
            if route == "/api/train":
                model = train(self.store, mode, str(data.get("heldout_group", "")), data.get("profile_key"))
                return {"model_id": model["model_id"], "report": model["report"]}
            if route == "/api/bookmark":
                return {"saved_scan_ids": self.store.bookmark(mode, str(data.get("scan_id", "")), data.get("saved", True))}
            if route == "/api/predict":
                model = self.store.load_model(mode)
                if not model:
                    raise ValueError("Train a model in this workspace first.")
                scan = self.store.get(mode, str(data.get("scan_id", "")))
                return predict(model, scan)
            raise ValueError("Unknown API action.")


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def valid_host(self):
            port = self.server.server_port
            return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def valid_origin(self):
            origin = self.headers.get("Origin")
            return not origin or origin in app.allowed_origins or origin in {
                f"http://localhost:{self.server.server_port}", f"http://127.0.0.1:{self.server.server_port}"}

        def error(self, status, message, code="invalid_request"):
            self.send(status, {"error": message, "code": code})

        def send(self, status, body, content_type="application/json", extra=None):
            if content_type == "application/json":
                body = json.dumps(body, allow_nan=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin")
            if origin and self.valid_origin():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.valid_host():
                return self.error(403, "Use the local Olfy URL printed in Terminal.", "forbidden_host")
            if not self.valid_origin():
                return self.error(403, "This browser origin is not allowed.", "forbidden_origin")
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/v1/"):
                path = "/api/" + path[len("/api/v1/"):]
            query = parse_qs(parsed.query)
            mode = query.get("mode", ["simulation"])[0]
            try:
                if path == "/api/setup":
                    return self.send(200, setup_status(app.store, app.recorder))
                if path == "/api/plan":
                    return self.send(200, {"plan": load_plan(app.store), "rows": plan_rows(app.store)})
                if path == "/api/plan/export":
                    return self.send(200, plan_csv(app.store), "text/csv; charset=utf-8",
                                     {"Content-Disposition": 'attachment; filename="Olfy_Experiment_Plan.csv"'})
                if path == "/api/state":
                    return self.send(200, app.state(mode))
                if path == "/api/status":
                    return self.send(200, {"api_version": 1, **app.recorder.status()})
                if path == "/api/adapters":
                    return self.send(200, inventory(app.recorder.registry))
                if path == "/api/schema":
                    return self.send(200, openapi())
                if path == "/api/catalogue":
                    return self.send(200, app.store.catalogue.snapshot(query.get("id", [None])[0]))
                if path == "/api/catalogue/samples":
                    return self.send(200, app.store.catalogue.samples(query.get("id", [""])[0]))
                if path == "/api/readiness":
                    return self.send(200, app.store.catalogue.readiness(app.store, query.get("mode", ["real"])[0]))
                if path == "/api/backup":
                    return self.send(200, app.backup(), "application/zip",
                                     {"Content-Disposition": 'attachment; filename="Olfy_Data_Backup.zip"'})
                if path == "/api/health":
                    return self.send(200, {"app_id": "olfy-local", "software_version": __version__,
                        "workspace_key": hashlib.sha256(str(app.store.directory.resolve()).encode()).hexdigest(),
                        "catalogue": app.store.catalogue.summary(),
                        "capabilities": {"recording": True, "reference_collection": True, "training": True,
                            "perfume_accuracy_validated": False, "wireless_accessory": False},
                        "hardware_connected": app.recorder.status()["connected_mode"] == "real"})
                if path == "/api/model-runs":
                    return self.send(200, {"mode": mode, "runs": app.store.model_runs(mode)})
                if path == "/api/model-run":
                    return self.send(200, app.store.model_run(mode, query.get("id", [""])[0]))
                if path == "/api/catalogue/export":
                    return self.send(200, app.store.catalogue.export_bytes(), "application/vnd.sqlite3",
                                     {"Content-Disposition": 'attachment; filename="Olfy_Reference_50.sqlite3"'})
                if path == "/api/scan":
                    scan = app.store.get(mode, query.get("id", [""])[0])
                    try:
                        _, scan["qc"] = extract(scan)
                    except ValueError as exc:
                        scan["qc"] = {"warnings": [str(exc)]}
                    return self.send(200, scan)
                if path == "/api/export":
                    return self.send(200, app.store.export_csv(mode), "text/csv; charset=utf-8",
                                     {"Content-Disposition": f'attachment; filename="olfy_{mode}.csv"'})
                consumer = (WEB / "consumer").resolve()
                if parsed.path == "/" and (consumer / "index.html").is_file():
                    return self.send(200, (consumer / "index.html").read_bytes(), "text/html; charset=utf-8")
                if parsed.path.startswith("/consumer/"):
                    asset = (consumer / unquote(parsed.path[len("/consumer/"):])).resolve()
                    if asset.is_relative_to(consumer) and asset.is_file() and asset.suffix in {".html", ".js", ".css", ".svg", ".woff2", ".woff", ".ttf", ".txt", ".png", ".jpg"}:
                        mime = "text/javascript; charset=utf-8" if asset.suffix == ".js" else mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
                        return self.send(200, asset.read_bytes(), mime)
                    return self.error(404, "Not found.", "not_found")
                files = {"/": ("scan.html", "text/html; charset=utf-8"),
                         "/setup": ("setup.html", "text/html; charset=utf-8"),
                         "/setup/": ("setup.html", "text/html; charset=utf-8"),
                         "/setup.js": ("setup.js", "text/javascript; charset=utf-8"),
                         "/setup.css": ("setup.css", "text/css; charset=utf-8"),
                         "/classic": ("scan.html", "text/html; charset=utf-8"),
                         "/lab": ("index.html", "text/html; charset=utf-8"),
                         "/lab/": ("index.html", "text/html; charset=utf-8"),
                         "/scan.js": ("scan.js", "text/javascript; charset=utf-8"),
                         "/scan.css": ("scan.css", "text/css; charset=utf-8"),
                         "/icon.svg": ("icon.svg", "image/svg+xml"),
                         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                         "/olfy-client.js": ("olfy-client.js", "text/javascript; charset=utf-8"),
                         "/styles.css": ("styles.css", "text/css; charset=utf-8")}
                if parsed.path in files:
                    name, mime = files[parsed.path]
                    return self.send(200, (WEB / name).read_bytes(), mime)
                self.error(404, "Not found.", "not_found")
            except (ValueError, TypeError) as exc:
                self.error(400, str(exc))
            except (OSError, RuntimeError) as exc:
                self.error(503, str(exc), "storage_unavailable")

        def do_OPTIONS(self):
            if not self.valid_host() or not self.headers.get("Origin") or not self.valid_origin():
                return self.error(403, "This browser origin is not allowed.", "forbidden_origin")
            requested = {h.strip().lower() for h in self.headers.get("Access-Control-Request-Headers", "").split(",") if h.strip()}
            if not requested <= {"content-type", "x-olfy-token"} or self.headers.get("Access-Control-Request-Method") not in ("GET", "POST"):
                return self.error(403, "Unsupported preflight request.", "forbidden_origin")
            self.send(204, b"", "text/plain", {"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                              "Access-Control-Allow-Headers": "Content-Type, X-Olfy-Token"})

        def do_POST(self):
            if not self.valid_host():
                return self.error(403, "Use the local Olfy URL.", "forbidden_host")
            if not self.valid_origin():
                return self.error(403, "Cross-site requests are blocked.", "forbidden_origin")
            if self.headers.get("X-Olfy-Token") != app.token:
                return self.error(403, "Reload the dashboard before making changes.", "invalid_token")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("JSON body must be between 1 and 65536 bytes.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object.")
                self.send(200, app.action(urlparse(self.path).path, data))
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                self.error(400, str(exc), "sensor_unavailable" if isinstance(exc, (RuntimeError, OSError)) else "invalid_request")
            except Exception as exc:
                self.log_error("Operation failed: %s", exc)
                self.error(500, "Operation failed. See Terminal for details.", "internal_error")

        def log_message(self, fmt, *args):
            # The dashboard polls once per second; retain failures without noisy access logs.
            if len(args) > 1 and str(args[1]).startswith(("4", "5")):
                super().log_message(fmt, *args)

    return Handler


def make_server(directory, port=8765, registry=None, allowed_origins=()):
    app = App(directory, registry=registry, allowed_origins=allowed_origins)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(app))
    except Exception:
        app.close()
        raise
    original_close = server.server_close
    def close_server():
        try:
            original_close()
        finally:
            app.close()
    server.server_close = close_server
    return app, server
