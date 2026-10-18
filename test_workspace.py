"""Preparation regression checks; all sensor data here is generated in temp folders."""
import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from olfy.__main__ import running_app_url
from olfy.backup import create_backup, restore_backup
from olfy.client import OlfyClient, OlfyError
from olfy.demo import seed_demo
from olfy.model import train
from olfy.server import App, make_server
from olfy.storage import Store
from olfy.workspace import load_plan, plan_csv, plan_rows, save_plan, setup_status


def proposed(store):
    return {"fragrance_ids": [f["fragrance_id"] for f in store.catalogue.snapshot()["fragrances"][:2]],
            "substrate": "paper blotter", "dose": "1 spray, fixed chamber", "drydown_min": 5,
            "start_date": "2026-11-01"}


class PlanTests(unittest.TestCase):
    def test_plan_persists_without_measurements_and_roundtrips_in_full_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/"source")
            plan = save_plan(store, proposed(store))
            rows = plan_rows(store)
            self.assertEqual(len(rows),21)
            self.assertEqual(len({r["sample_id"] for r in rows}),21)
            self.assertEqual(plan["collection_days"],["2026-11-01","2026-11-02","2026-11-03"])
            self.assertEqual(sum(r["kind"]=="known" for r in rows),18)
            self.assertEqual(sum(r["kind"]=="blank" for r in rows),3)
            self.assertEqual(sum(r["kind"]=="unknown" for r in rows),0)
            self.assertEqual(store.list("real"),[])
            self.assertEqual(store.catalogue.summary()["reference_count"],0)
            self.assertEqual(load_plan(Store(store.directory)),plan)
            backup = Path(tmp)/"backup.zip"
            backup.write_bytes(create_backup(store))
            restored_dir = Path(tmp)/"restored"
            restore_backup(backup,restored_dir)
            restored = Store(restored_dir)
            self.assertEqual(load_plan(restored),plan)
            self.assertEqual(plan_rows(restored),rows)
            self.assertEqual(restored.list("real"),[])
            save_plan(store,{**proposed(store),"include_unknown_control":True})
            self.assertEqual(len(plan_rows(store)),24)
            self.assertEqual(sum(r["kind"]=="unknown" for r in plan_rows(store)),3)

    def test_invalid_plan_does_not_replace_saved_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            valid = proposed(store)
            saved = save_plan(store,valid)
            invalid = [
                {"fragrance_ids": valid["fragrance_ids"][:1]},
                {"fragrance_ids": [valid["fragrance_ids"][0]]*2},
                {"fragrance_ids": [valid["fragrance_ids"][0],"invented-perfume"]},
                {"fragrance_ids": [None,True]},
                {"drydown_min": float("nan")}, {"drydown_min": True},
                {"start_date":"2026-02-30"}, {"start_date":"9999-12-31"},
                {"substrate":" "}, {"dose":"x"*121}, {"unexpected":"field"},
                {"include_unknown_control":1},
            ]
            for changes in invalid:
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    save_plan(store,{**valid,**changes})
                self.assertEqual(load_plan(store),saved)

    def test_csv_keeps_catalogue_ids_and_neutralizes_user_formulas(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            save_plan(store,{**proposed(store),"dose":" =HYPERLINK(\"example\")"})
            rows = list(csv.DictReader(io.StringIO(plan_csv(store))))
            self.assertEqual(len(rows),21)
            self.assertTrue(rows[0]["dose"].startswith("'="))
            self.assertEqual(rows[0]["fragrance_id"],load_plan(store)["fragrance_ids"][0])
            self.assertIn("PLANNED ONLY",rows[0]["notes"])
            self.assertTrue(load_plan(store)["dose"].startswith("="))

    def test_prior_workspace_schema_migrates_without_resetting_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            sid = store.create("real",{"label":"retained interrupted sample","group_id":"earlier-day"})
            store.finish("real",sid,"aborted")
            with store.connect("real") as db:
                db.execute("DROP TABLE workspace_settings")
            migrated = Store(tmp)
            self.assertEqual(migrated.get("real",sid)["status"],"aborted")
            self.assertIsNone(load_plan(migrated))
            self.assertEqual(migrated.catalogue.summary()["perfume_count"],50)


class WorkspaceTests(unittest.TestCase):
    def test_checks_do_not_connect_hardware_and_missing_drivers_are_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp)
            try:
                with patch("olfy.workspace.package_version",side_effect=lambda name:"test" if name in ("numpy","scikit-learn") else None),patch.object(app.recorder.registry,"create",side_effect=AssertionError("must not connect")):
                    result = setup_status(app.store,app.recorder)
                self.assertTrue(result["software_ready"])
                self.assertFalse(result["hardware"]["connected"])
                self.assertFalse(result["hardware"]["bme688_drivers_installed"])
                self.assertEqual(result["catalogue"]["reference_count"],0)
                self.assertEqual(result["real_scans"],0)
                self.assertFalse(result["limits"]["perfume_accuracy_validated"])
            finally:app.close()

    def test_unwritable_storage_is_not_reported_as_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp)
            try:
                with patch("olfy.workspace.tempfile.TemporaryFile",side_effect=PermissionError("read only")):
                    result = setup_status(app.store,app.recorder)
                self.assertFalse(result["software_ready"])
                self.assertEqual(next(c for c in result["checks"] if c["id"]=="storage")["status"],"action")
            finally:app.close()

    def test_practice_is_isolated_from_existing_scans_plan_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp)
            try:
                seed_demo(app.store)
                model = train(app.store,"simulation","demo-day-3")
                plan = save_plan(app.store,proposed(app.store))
                app.store.bookmark("simulation",model["train_scan_ids"][0],True)
                scans = app.store.list("simulation")
                bookmarks = app.store.bookmarks("simulation")
                with patch.object(app.recorder.registry,"create",side_effect=AssertionError("must not connect")):
                    result = app.action("/api/v1/practice",{"mode":"simulation"})
                self.assertTrue(result["passed"])
                self.assertTrue(result["isolated"])
                self.assertEqual(len(result["checks"]),6)
                self.assertEqual(app.store.list("simulation"),scans)
                self.assertEqual(app.store.load_model("simulation"),model)
                self.assertEqual(app.store.bookmarks("simulation"),bookmarks)
                self.assertEqual(load_plan(app.store),plan)
                self.assertEqual(app.store.list("real"),[])
                self.assertEqual(app.store.catalogue.summary()["reference_count"],0)
            finally:app.close()

    def test_practice_and_plan_changes_refused_during_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp)
            try:
                sid = app.recorder.start("simulation",{"label":"Demo A","group_id":"practice-day"})
                for route,data in (("practice",{"mode":"simulation"}),("plan",{**proposed(app.store),"mode":"real"})):
                    with self.subTest(route=route),self.assertRaisesRegex(ValueError,"current recording"):
                        app.action("/api/v1/"+route,data)
                self.assertEqual(app.recorder.status()["active"]["id"],sid)
                app.recorder.finish(abort=True,mode="simulation",scan_id=sid)
                self.assertIsNone(load_plan(app.store))
                with self.assertRaisesRegex(ValueError,"simulation"):
                    app.action("/api/v1/practice",{"mode":"real"})
            finally:app.close()

    def test_http_plan_sdk_static_routes_and_existing_instance_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,server = make_server(tmp,0)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            client = OlfyClient(url)
            try:
                self.assertTrue(client.setup()["software_ready"])
                self.assertEqual(client.experiment_plan(),{"plan":None,"rows":[]})
                saved = client.save_experiment_plan(proposed(app.store))["plan"]
                self.assertEqual(client.experiment_plan()["plan"],saved)
                self.assertEqual(running_app_url(server.server_port,Path(tmp)),url)
                self.assertIsNone(running_app_url(server.server_port,Path(tmp)/"different-data"))
                for route in ("/setup","/setup/","/setup.js","/setup.css","/lab?mode=real&tab=record"):
                    with urlopen(url+route) as response:self.assertEqual(response.status,200)
                with urlopen(url+"/api/v1/plan/export") as response:
                    self.assertIn("text/csv",response.headers["Content-Type"])
                    self.assertIn("PLANNED ONLY",response.read().decode())
                with urlopen(url+"/api/v1/schema") as response:schema=json.load(response)
                self.assertIn("/api/v1/setup",schema["paths"])
                self.assertIn("post",schema["paths"]["/api/v1/plan"])
                request=Request(url+"/api/v1/plan",data=json.dumps(proposed(app.store)).encode(),headers={"Content-Type":"application/json"})
                with self.assertRaises(HTTPError) as caught:urlopen(request)
                self.assertEqual(caught.exception.code,403)
                self.assertEqual(client.experiment_plan()["plan"],saved)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)
