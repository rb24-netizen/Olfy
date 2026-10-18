import argparse
from pathlib import Path
import webbrowser
import json
import hashlib
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from .adapters import default_registry, inventory
from .contracts import normalize_sample

from .server import make_server, App
from .backup import WorkspaceLock, create_backup, restore_backup
from .storage import Store
from .workspace import setup_status


def running_app_url(port, directory):
    """Reuse only an Olfy instance serving this exact resolved data folder."""
    url = f"http://127.0.0.1:{port}"
    expected = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
    try:
        with urlopen(url + "/api/v1/health", timeout=1) as response:
            status = json.loads(response.read(65536))
        if status.get("app_id") == "olfy-local" and status.get("workspace_key") == expected:
            return url
    except (URLError, HTTPError, OSError, ValueError, AttributeError):
        pass
    return None


def print_checks(report):
    print(f"\nOlfy {report['software_version']} - workspace checks\n")
    for check in report["checks"]:
        print(f"  {check['status'].upper():6}  {check['label']}: {check['detail']}")
    hardware = report["hardware"]
    print(f"\n  Hardware: {'connected' if hardware['connected'] else 'not connected (not needed for practice)'}")
    print(f"  BME688 drivers: {'installed' if hardware['bme688_drivers_installed'] else 'optional; bash start.sh --hardware --prepare'}")
    print(f"  USB serial driver: {'installed' if hardware['serial_driver_installed'] else 'optional; bash start.sh --serial --prepare'}")
    print(f"  Data: {report['data_directory']}")
    print(f"  Real scans: {report['real_scans']}; measured perfume references: {report['catalogue']['reference_count']}")
    print("\n  Physical sensor compatibility and perfume accuracy still require real measurements.\n")


def main():
    parser = argparse.ArgumentParser(description="Olfy local research workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / "data")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--setup", action="store_true", help="Open the guided preparation screen")
    parser.add_argument("--doctor", action="store_true", help="Check the workspace without connecting a sensor")
    parser.add_argument("--reuse-running", action="store_true", help="Open an existing instance only when it serves the same data folder")
    parser.add_argument("--allow-origin", action="append", default=[], help="Allow an exact local browser-app origin for integration")
    parser.add_argument("--list-sensors", action="store_true", help="List available adapters and USB/serial devices")
    parser.add_argument("--check-sensor", action="store_true", help="Connect, validate one sample and disconnect")
    parser.add_argument("--adapter", choices=("bme688", "serial"), default="bme688")
    parser.add_argument("--address", default="auto")
    parser.add_argument("--device-id", default="")
    parser.add_argument("--serial-port", default="auto")
    parser.add_argument("--baud-rate", type=int, default=115200)
    parser.add_argument("--backup-to", type=Path, help="Save a complete data backup without starting the server")
    parser.add_argument("--restore-backup", type=Path, help="Restore into a new empty --data-dir without overwriting recordings")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    if args.backup_to or args.restore_backup:
        if args.backup_to and args.restore_backup:
            parser.error("Choose backup or restore, not both.")
        try:
            with WorkspaceLock(args.data_dir):
                if args.restore_backup:
                    manifest = restore_backup(args.restore_backup, args.data_dir)
                    print(f"Restored {manifest['counts']} into {args.data_dir.resolve()}")
                else:
                    if args.backup_to.exists():
                        raise ValueError("Backup destination already exists. Choose a new filename.")
                    args.backup_to.parent.mkdir(parents=True, exist_ok=True)
                    args.backup_to.write_bytes(create_backup(Store(args.data_dir)))
                    print(f"Backup saved: {args.backup_to.resolve()}")
        except (OSError, ValueError) as exc:
            parser.exit(1, f"Data operation failed: {exc}\n")
        return
    if args.list_sensors:
        print(json.dumps(inventory(default_registry()), indent=2))
        return
    if args.check_sensor:
        sensor = None
        try:
            config = {"address": args.address, "device_id": args.device_id} if args.adapter == "bme688" else {"port": args.serial_port, "baud_rate": args.baud_rate}
            sensor = default_registry().create(args.adapter, config)
            print(json.dumps({"connected": True, "sensor": sensor.info.to_dict(),
                              "reading": normalize_sample(sensor.info, sensor.read("baseline", 0)),
                              "note": "Connection check only; condition and warm up before experiments."}, indent=2))
        except (ValueError, RuntimeError, OSError) as exc:
            parser.exit(1, f"Sensor check failed: {exc}\n")
        finally:
            if sensor:
                sensor.close()
        return
    existing_url = running_app_url(args.port, args.data_dir) if args.reuse_running or args.doctor else None
    if args.doctor:
        app = None
        try:
            if existing_url:
                with urlopen(existing_url + "/api/v1/setup", timeout=10) as response:
                    report = json.load(response)
            else:
                app = App(args.data_dir)
                report = setup_status(app.store, app.recorder)
            print_checks(report)
            if not report["software_ready"]:
                parser.exit(1, "A workspace check needs attention.\n")
        except (OSError, RuntimeError, ValueError) as exc:
            parser.exit(1, f"Workspace check failed: {exc}\n")
        finally:
            if app:
                app.close()
        return
    if existing_url:
        url = existing_url + ("/setup" if args.setup else "/")
        print(f"Olfy is already running. Open {url}\nKeep its existing Terminal window open.", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return
    first_run = not (args.data_dir / "real.sqlite3").exists()
    try:
        app, server = make_server(args.data_dir, args.port, allowed_origins=args.allow_origin)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not start Olfy: {exc}\nTry --port 8766 if the port is occupied.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"\nOlfy is running at {url}\nData: {args.data_dir.resolve()}\nPress Ctrl+C to stop.\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url + ("/setup" if args.setup or first_run else "/"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Olfy and preserving recordings.")
    finally:
        server.server_close()
        app.recorder.close()


if __name__ == "__main__":
    main()
