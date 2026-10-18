import json
import secrets
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from olfy.adapters import AdapterRegistry, AdapterSpec, default_registry
from olfy.client import OlfyClient, OlfyError
from olfy.contracts import SensorInfo, UNITS, normalize_sample
from olfy.recorder import Recorder
from olfy.sensors import BME688Sensor
from olfy.serial_sensor import SerialSensor
from olfy.server import make_server
from olfy.storage import Store


class StubSensor:
    """Stub transport for software verification; no physical data is claimed."""
    def __init__(self):
        self.info=SensorInfo("stub", "hardware-test-01", "test-profile-v1",
                             units={**UNITS,"second_gas_ohm":"ohm"})
        self.closed=False
        self.fail=False

    def read(self, phase, seconds):
        if self.fail:raise OSError("USB disconnected")
        return {"gas_ohm":100000+seconds*100, "extra_channels":{"second_gas_ohm":90000},
                "phase":"untrusted", "sequence":999, "elapsed_s":-1}

    def close(self):self.closed=True


def stub_registry(sensor):
    registry=default_registry()
    registry.register(AdapterSpec("stub", "Test-only stub", "real", lambda:sensor))
    return registry


class ContractTests(unittest.TestCase):
    def test_registry_contract_rejects_wrong_units_mode_and_options(self):
        registry=default_registry()
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            registry.create("simulation",{"unknown_option":1})
        with self.assertRaisesRegex(ValueError,"object"):
            registry.create("simulation",[])
        source=StubSensor();source.info=SensorInfo("stub","test","profile",units={"gas_ohm":"kohm"})
        registry.register(AdapterSpec("stub","Invalid stub","real",lambda:source))
        with self.assertRaisesRegex(ValueError,"in ohms"):
            registry.create("stub")
        self.assertTrue(source.closed)
        with tempfile.TemporaryDirectory() as tmp:
            recorder=Recorder(Store(tmp))
            try:
                with self.assertRaisesRegex(ValueError,"simulation adapter"):
                    recorder.connect("simulation")
                self.assertIsNone(recorder.status()["sensor"])
            finally:recorder.close()

    def test_measurement_validation_and_metadata_whitelist(self):
        source=StubSensor()
        result=normalize_sample(source.info,source.read("baseline",0))
        self.assertNotIn("phase",result)
        self.assertNotIn("elapsed_s",result)
        self.assertNotIn("sequence",result)
        self.assertEqual(result["extra_channels"]["second_gas_ohm"],90000)
        for value in (True,float("nan"),0,"100000"):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_sample(source.info,{"gas_ohm":value})

    def test_failed_first_read_closes_adapter_without_connection(self):
        source=StubSensor();source.fail=True
        with tempfile.TemporaryDirectory() as tmp:
            recorder=Recorder(Store(tmp),registry=stub_registry(source))
            try:
                with self.assertRaisesRegex(OSError,"disconnected"):recorder.connect("stub")
                self.assertTrue(source.closed)
                self.assertIsNone(recorder.status()["sensor"])
            finally:recorder.close()


class BmeConnectionTests(unittest.TestCase):
    def modules(self, addresses, bridges=1):
        self.bus=types.SimpleNamespace(try_lock=lambda:True,unlock=lambda:None,scan=lambda:addresses,deinit=lambda:setattr(self,"deinitialized",True))
        self.deinitialized=False
        def driver(bus,address,refresh_rate):
            self.selected_address=address
            return types.SimpleNamespace(set_gas_heater=lambda temp,ms:True,gas=100000,temperature=23,relative_humidity=40,pressure=1013)
        return {"board":types.SimpleNamespace(I2C=lambda:self.bus),
                "adafruit_bme680":types.SimpleNamespace(Adafruit_BME680_I2C=driver),
                "hid":types.SimpleNamespace(enumerate=lambda vid,pid:[{"serial_number":f"bridge-{i}"} for i in range(bridges)])}

    def test_auto_address_detects_76_and_records_identity(self):
        with patch.dict("sys.modules",self.modules([0x76])):
            sensor=BME688Sensor()
            self.assertEqual(self.selected_address,0x76)
            self.assertEqual(sensor.info.transport["address"],"0x76")
            self.assertIn("bridge-0",sensor.info.device_id)
            self.assertEqual(sensor.read("baseline",0)["gas_ohm"],100000)
            sensor.close();self.assertTrue(self.deinitialized)

    def test_ambiguous_or_missing_hardware_fails_cleanly(self):
        for addresses,bridges in (([],1),([0x76,0x77],1),([0x77],2)):
            with self.subTest(addresses=addresses,bridges=bridges),patch.dict("sys.modules",self.modules(addresses,bridges)):
                with self.assertRaises(RuntimeError):BME688Sensor()
                if bridges==1:self.assertTrue(self.deinitialized)


class SerialConnectionTests(unittest.TestCase):
    def packet(self,**changes):
        return {"type":"olfy.sample","schema_version":1,"device_id":"serial-test-01",
                "profile":"test-serial-profile-v1","gas_ohm":100000,"source_sequence":1,**changes}

    def modules(self, packets):
        lines=[p if isinstance(p,bytes) else (json.dumps(p)+"\n").encode() for p in packets]
        self.connection=types.SimpleNamespace(readline=lambda size:lines.pop(0) if lines else b"",
            reset_input_buffer=lambda:None,in_waiting=0,close=lambda:setattr(self,"closed",True))
        self.closed=False
        serial=types.ModuleType("serial");serial.Serial=lambda *args,**kwargs:self.connection
        tools=types.ModuleType("serial.tools");tools.list_ports=types.SimpleNamespace(comports=lambda:[])
        return {"serial":serial,"serial.tools":tools}

    def test_handshake_and_fresh_samples(self):
        with patch.dict("sys.modules",self.modules([b"Booting\n",self.packet(),self.packet(source_sequence=2,gas_ohm=80000)])):
            source=SerialSensor(port="/dev/test-sensor")
            self.assertEqual(source.info.device_id,"serial-test-01")
            self.assertEqual(source.read("baseline",0)["source_sequence"],1)
            self.assertEqual(source.read("exposure",1)["gas_ohm"],80000)
            with self.assertRaisesRegex(RuntimeError,"timed out"):source.read("recovery",2)
            source.close();self.assertTrue(self.closed)

    def test_duplicate_sequence_and_changed_profile_rejected(self):
        for second in (self.packet(),self.packet(source_sequence=2,profile="changed")):
            with self.subTest(second=second),patch.dict("sys.modules",self.modules([self.packet(),second])):
                source=SerialSensor(port="/dev/test-sensor")
                source.read("baseline",0)
                with self.assertRaises(ValueError):source.read("exposure",1)
                source.close()

    def test_invalid_units_synthetic_and_malformed_handshake_closed(self):
        for first in (self.packet(units={"gas_ohm":"kohm"}),self.packet(mode="simulation"),self.packet(schema_version=2),self.packet(gas_ohm=float("nan"))):
            with self.subTest(first=first),patch.dict("sys.modules",self.modules([first])):
                with self.assertRaises(ValueError):SerialSensor(port="/dev/test-sensor")
                self.assertTrue(self.closed)


class ApiIntegrationTests(unittest.TestCase):
    def wait_for(self, predicate):
        deadline=time.monotonic()+4
        while not predicate():
            if time.monotonic()>deadline:self.fail("Expected acquisition state did not arrive")
            time.sleep(.01)

    def test_sdk_custom_adapter_recording_identity_stale_commands_and_token_refresh(self):
        source=StubSensor()
        with tempfile.TemporaryDirectory() as tmp:
            app,server=make_server(tmp,0,registry=stub_registry(source),allowed_origins=("http://localhost:3000",))
            app.recorder.interval=.01
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            client=OlfyClient(f"http://127.0.0.1:{server.server_port}")
            try:
                self.assertIn("stub",[a["adapter_id"] for a in client.adapters()["adapters"]])
                self.assertEqual(client.connect_sensor("stub")["sensor"]["profile"],"test-profile-v1")
                client.token="expired-token" # This rejected write must be retried only once.
                scan_id=client.start_scan({"label":"Test perfume","group_id":"test-day","bottle_id":"bottle-01","warmup_ack":True})["scan_id"]
                self.assertEqual(len(app.store.list("real")),1)
                with self.assertRaises(OlfyError):client.next_phase("stale-id")
                with self.assertRaises(OlfyError):client.next_phase(scan_id,mode="simulation")
                self.assertEqual(client.status()["active"]["phase"],"baseline")
                for phase in ("baseline","exposure","recovery"):
                    self.wait_for(lambda:client.status()["active"]["counts"].get(phase,0)>=9)
                    if phase!="recovery":client.next_phase(scan_id)
                client.finish_scan(scan_id)
                scan=client.get_scan(scan_id)
                self.assertEqual(scan["status"],"complete")
                self.assertEqual(scan["device_id"],"hardware-test-01")
                self.assertEqual(scan["profile"],"test-profile-v1")
                self.assertEqual(scan["sensor"]["units"]["second_gas_ohm"],"ohm")
                self.assertGreaterEqual(len(scan["readings"]),27)
                self.assertEqual(scan["readings"][0]["phase"],"baseline")
                self.assertGreaterEqual(scan["readings"][0]["elapsed_s"],0)
                self.assertEqual(client.state("simulation")["scans"],[])
                client.disconnect();self.assertTrue(source.closed)
            finally:server.shutdown();server.server_close();app.recorder.close();thread.join(timeout=3)

    def test_disconnect_preserves_error_scan_without_fallback(self):
        source=StubSensor()
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);recorder=Recorder(store,interval=.01,registry=stub_registry(source))
            try:
                recorder.connect("stub")
                scan_id=recorder.start("real",{"label":"Test","group_id":"day-1","bottle_id":"b1","warmup_ack":True})
                self.wait_for(lambda:recorder.status()["active"]["counts"].get("baseline",0)>=2)
                source.fail=True
                self.wait_for(lambda:recorder.status()["active"] is None)
                self.assertEqual(store.get("real",scan_id)["status"],"error")
                self.assertIn("disconnected",recorder.status()["error"])
                self.assertEqual(store.list("simulation"),[])
                self.assertTrue(source.closed)
            finally:recorder.close()

    def test_quick_capture_auto_saves_raw_and_stays_out_of_reference_training(self):
        source=StubSensor()
        with tempfile.TemporaryDirectory() as tmp:
            app,server=make_server(tmp,0,registry=stub_registry(source))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            client=OlfyClient(f"http://127.0.0.1:{server.server_port}")
            metadata={"label":"Unlabelled capture","group_id":"quick-day","bottle_id":"unknown-source","warmup_ack":True}
            try:
                client.connect_sensor("stub")
                for duration in (None,False,0,61):
                    with self.subTest(duration=duration),self.assertRaises(OlfyError):client.start_capture(metadata,duration_s=duration)
                with self.assertRaises(OlfyError):client.start_capture({**metadata,"warmup_ack":False})
                self.assertEqual(client.state("real")["scans"],[])
                sid=client.start_capture(metadata,duration_s=5)["scan_id"]
                self.assertEqual(client.status()["active"]["capture_mode"],"quick")
                with self.assertRaises(OlfyError):client.next_phase(sid)
                with self.assertRaises(OlfyError):client.finish_scan(sid)
                deadline=time.monotonic()+8
                while client.status()["active"] is not None:
                    if time.monotonic()>deadline:self.fail("Quick capture did not finish automatically")
                    time.sleep(.05)
                scan=client.get_scan(sid)
                self.assertEqual(scan["status"],"captured")
                self.assertEqual(scan["acquisition_protocol"],"quick-capture-v1")
                self.assertEqual(scan["device_id"],"hardware-test-01")
                self.assertEqual(scan["kind"],"unknown")
                self.assertGreaterEqual(scan["readings"][-1]["elapsed_s"],5)
                self.assertTrue(all(r["phase"]=="exposure" for r in scan["readings"]))
                self.assertIn("second_gas_ohm",scan["readings"][0]["extra_channels"])
                self.assertEqual(client.status()["connected_mode"],"real")
                self.assertEqual(client.state("simulation")["scans"],[])
                with self.assertRaises(OlfyError):client.train("quick-day")
                sid2=client.start_capture(metadata,duration_s=5)["scan_id"]
                client.finish_scan(sid2,abort=True)
                self.assertEqual(client.get_scan(sid2)["status"],"aborted")
            finally:server.shutdown();server.server_close();app.recorder.close();thread.join(timeout=3)

    def test_versioned_schema_cors_and_unscoped_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,server=make_server(tmp,0,allowed_origins=("http://localhost:3000",))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base+"/api/v1/schema") as response:
                    schema=json.load(response)
                    self.assertEqual(schema["openapi"],"3.0.3")
                    self.assertIn("/api/v1/connect",schema["paths"])
                with urlopen(Request(base+"/api/v1/state",headers={"Origin":"http://localhost:3000"})) as response:
                    token=json.load(response)["csrf_token"]
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"],"http://localhost:3000")
                request=Request(base+"/api/v1/start",method="OPTIONS",headers={"Origin":"http://localhost:3000","Access-Control-Request-Method":"POST","Access-Control-Request-Headers":"content-type,x-olfy-token"})
                with urlopen(request) as response:self.assertEqual(response.status,204)
                with self.assertRaises(HTTPError):urlopen(Request(base+"/api/v1/state",headers={"Origin":"https://example.com"}))
                request=Request(base+"/api/v1/abort",data=b'{"mode":"simulation"}',headers={"Content-Type":"application/json","X-Olfy-Token":token})
                with self.assertRaises(HTTPError) as result:urlopen(request)
                self.assertEqual(result.exception.code,400)
            finally:server.shutdown();server.server_close();app.recorder.close();thread.join(timeout=3)


if __name__=="__main__":unittest.main()
