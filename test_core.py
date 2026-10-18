import copy
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from olfy.demo import seed_demo
from olfy.features import extract
from olfy.model import infer, predict, train
from olfy.recorder import Recorder
from olfy.server import make_server
from olfy.storage import Store


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory()
        cls.store=Store(cls.temporary.name)
        seed_demo(cls.store)
        cls.model=train(cls.store,"simulation","demo-day-4")
        cls.test_id=next(s["id"] for s in cls.store.list("simulation")
                         if s["group_id"]=="demo-day-4" and s["kind"]=="known")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_seed_idempotent_and_workspace_isolation(self):
        self.assertEqual(len(self.store.list("simulation")),68)
        self.assertEqual(self.store.list("real"),[])
        self.assertEqual(seed_demo(self.store)["created"],0)
        self.assertIsNone(self.store.load_model("real"))
        with self.assertRaisesRegex(ValueError,"not found"):
            self.store.get("real",self.test_id)

    def test_whole_day_is_held_out(self):
        train_ids=set(self.model["train_scan_ids"])
        test_ids={r["scan_id"] for r in self.model["report"]["results"]}
        self.assertFalse(train_ids & test_ids)
        self.assertNotIn("demo-day-4",self.model["train_groups"])
        self.assertEqual(self.model["report"]["train_count"],45)
        self.assertEqual(self.model["report"]["test_count"],17)
        self.assertEqual(self.model["report"]["unknown_count"],2)

    def test_saved_numeric_model_matches_sklearn(self):
        scans=[self.store.get("simulation",i) for i in self.model["train_scan_ids"]]
        x=np.array([extract(s)[0] for s in scans])
        scaler=StandardScaler().fit(x)
        classifier=LogisticRegression(C=1,max_iter=2000,random_state=0).fit(scaler.transform(x),[s["label"] for s in scans])
        query=self.store.get("simulation",self.test_id)
        scores=classifier.predict_proba(scaler.transform([extract(query)[0]]))[0]
        result=infer(self.store.load_model("simulation"),query)
        by_label={c["label"]:c["score"] for c in result["top_candidates"]}
        for label,value in zip(classifier.classes_,scores):
            if label in by_label:self.assertAlmostEqual(by_label[label],value,places=10)

    def test_training_sample_cannot_be_demonstrated_as_unseen(self):
        with self.assertRaisesRegex(ValueError,"used for training"):
            predict(self.model,self.store.get("simulation",self.model["train_scan_ids"][0]))

    def test_real_scan_cannot_use_simulation_model(self):
        scan=self.store.get("simulation",self.test_id);scan["mode"]="real"
        with self.assertRaisesRegex(ValueError,"simulation model"):
            predict(self.model,scan)

    def test_incomplete_invalid_and_reordered_scans_rejected(self):
        original=self.store.get("simulation",self.test_id)
        for mutation in ("incomplete","zero","nan","time","order"):
            scan=copy.deepcopy(original)
            if mutation=="incomplete":scan["status"]="aborted"
            if mutation=="zero":scan["readings"][2]["gas_ohm"]=0
            if mutation=="nan":scan["readings"][2]["gas_ohm"]=float("nan")
            if mutation=="time":scan["readings"][2]["elapsed_s"]=scan["readings"][1]["elapsed_s"]
            if mutation=="order":scan["readings"][0]["phase"]="exposure"
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):extract(scan)

    def test_unknown_and_blank_examples_can_be_rejected(self):
        # These controls verify software behavior, not real-world rejection performance.
        controls=[self.store.get("simulation",s["id"]) for s in self.store.list("simulation")
                  if s["group_id"]=="demo-day-4" and s["kind"]!="known"]
        for scan in controls:
            self.assertEqual(predict(self.model,scan)["decision"],"unknown")

    def test_device_and_duration_mismatch_rejected(self):
        scan=self.store.get("simulation",self.test_id);scan["device_id"]="unseen-sensor"
        result=predict(self.model,scan)
        self.assertEqual(result["decision"],"unknown")
        self.assertTrue(result["warnings"])
        scan=self.store.get("simulation",self.test_id)
        for r in scan["readings"]:r["elapsed_s"]*=2
        self.assertTrue(any("duration" in r for r in predict(self.model,scan)["reasons"]))

    def test_source_sample_overlap_blocks_training(self):
        scan=self.store.get("simulation",self.test_id)
        clone={k:v for k,v in scan.items() if k not in {"id","status","readings","created_at"}}
        clone["group_id"]="demo-day-1"
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);seed_demo(store)
            test=next(s for s in store.list("simulation") if s["group_id"]=="demo-day-4" and s["kind"]=="known")
            clone["sample_id"]=test["sample_id"]
            sid=store.create("simulation",clone)
            store.append_many("simulation",sid,scan["readings"]);store.finish("simulation",sid)
            with self.assertRaisesRegex(ValueError,"both training and testing"):
                train(store,"simulation","demo-day-4")

    def test_binary_model_probabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp)
            for s in self.store.list("simulation"):
                if s["label"] not in {"Demo A","Demo B"}:continue
                scan=self.store.get("simulation",s["id"])
                sid=store.create("simulation",scan)
                store.append_many("simulation",sid,scan["readings"]);store.finish("simulation",sid)
            model=train(store,"simulation","demo-day-4")
            query=next(store.get("simulation",s["id"]) for s in store.list("simulation") if s["group_id"]=="demo-day-4")
            result=predict(model,query)
            self.assertAlmostEqual(sum(c["score"] for c in result["top_candidates"]),1)
            self.assertEqual(result["top_candidates"][0]["label"],query["label"])


class RecordingTests(unittest.TestCase):
    def test_phase_guards_abort_and_no_synthetic_hardware_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);recorder=Recorder(store,interval=.01)
            try:
                with self.assertRaisesRegex(ValueError,"Connect the real sensor"):
                    recorder.start("real",{"label":"Oud Wood","group_id":"day-1"})
                sid=recorder.start("simulation",{"label":"Demo A","group_id":"day-1"})
                with self.assertRaisesRegex(ValueError,"at least 8"):
                    recorder.advance()
                with self.assertRaisesRegex(ValueError,"all three phases"):
                    recorder.finish()
                recorder.finish(abort=True)
                self.assertEqual(store.get("simulation",sid)["status"],"aborted")
                with patch.object(recorder.registry.specs["bme688"],"factory",side_effect=RuntimeError("USB unavailable")):
                    with self.assertRaisesRegex(RuntimeError,"USB unavailable"):recorder.connect_real()
                self.assertEqual(store.list("real"),[])
                self.assertIsNone(recorder.status()["connected_mode"])
            finally:recorder.close()

    def test_live_recording_finishes_with_all_raw_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);recorder=Recorder(store,interval=.01)
            try:
                sid=recorder.start("simulation",{"label":"Demo A","group_id":"day-1"})
                for phase in ("baseline","exposure","recovery"):
                    deadline=time.monotonic()+3
                    while recorder.status()["active"]["counts"].get(phase,0)<9:
                        if time.monotonic()>deadline:self.fail("Recorder did not acquire samples")
                        time.sleep(.01)
                    if phase!="recovery":recorder.advance()
                recorder.finish()
                scan=store.get("simulation",sid)
                self.assertEqual(scan["status"],"complete")
                self.assertGreaterEqual(len(scan["readings"]),27)
                self.assertEqual(len(extract(scan)[0]),12)
            finally:recorder.close()


class ApiTests(unittest.TestCase):
    def test_dashboard_api_export_and_request_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,server=make_server(tmp,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base+"/") as response:self.assertIn(b"Discover a scent",response.read())
                with urlopen(base+"/lab") as response:self.assertIn(b"Research workbench",response.read())
                with urlopen(base+"/olfy-client.js") as response:
                    self.assertIn(b"export class OlfyClient",response.read())
                with urlopen(base+"/api/state") as response:state=json.load(response)
                def post(route,data,token=None,origin=None):
                    headers={"Content-Type":"application/json"}
                    if token:headers["X-Olfy-Token"]=token
                    if origin:headers["Origin"]=origin
                    return urlopen(Request(base+route,data=json.dumps(data).encode(),headers=headers))
                with self.assertRaises(HTTPError) as result:post("/api/seed",{})
                self.assertEqual(result.exception.code,403)
                with self.assertRaises(HTTPError) as result:post("/api/seed",{},state["csrf_token"],"https://example.com")
                self.assertEqual(result.exception.code,403)
                with post("/api/seed",{},state["csrf_token"]) as response:self.assertEqual(json.load(response)["created"],68)
                with post("/api/train",{"heldout_group":"demo-day-4"},state["csrf_token"]) as response:self.assertEqual(json.load(response)["report"]["test_count"],17)
                with urlopen(base+"/api/export?mode=simulation") as response:
                    self.assertIn("text/csv",response.headers["Content-Type"])
                    self.assertIn(b"gas_ohm",response.read())
                with self.assertRaises(HTTPError):urlopen(base+"/../../requirements.txt")
                for path in ("/consumer/../styles.css", "/consumer/%2e%2e/server.py", "/consumer/../../data/real.sqlite3"):
                    with self.assertRaises(HTTPError) as result:urlopen(base+path)
                    self.assertEqual(result.exception.code,404)
            finally:
                server.shutdown();server.server_close();app.recorder.close();thread.join(timeout=3)


if __name__=="__main__":unittest.main()
