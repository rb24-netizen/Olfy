"""Dependency-free Python client for the stable local Olfy v1 API."""

import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OlfyError(RuntimeError):
    def __init__(self, message, code, status):
        super().__init__(message)
        self.code = code
        self.status = status


class OlfyClient:
    def __init__(self, base_url="http://127.0.0.1:8765", timeout=15):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.token = None

    def _request(self, endpoint, data=None, query=None, refresh_token=True):
        if data is not None and not self.token:
            self.token = self.state()["csrf_token"]
        url = self.base_url + "/" + endpoint
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": "application/json"}
        if data is not None:
            headers.update({"Content-Type": "application/json", "X-Olfy-Token": self.token})
        request = Request(url, data=json.dumps(data, allow_nan=False).encode() if data is not None else None, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            payload = json.loads(exc.read())
            # A rejected token means no mutation occurred, so one retry is safe.
            if exc.code == 403 and payload.get("code") == "invalid_token" and refresh_token:
                self.token = self.state()["csrf_token"]
                return self._request(endpoint, data, query, refresh_token=False)
            raise OlfyError(payload.get("error", str(exc)), payload.get("code", "http_error"), exc.code) from exc

    def state(self, mode="simulation"):
        return self._request("state", query={"mode": mode})

    def status(self):
        return self._request("status")

    def setup(self):
        return self._request("setup")

    def practice(self):
        return self._request("practice", {"mode": "simulation"})

    def experiment_plan(self):
        return self._request("plan")

    def save_experiment_plan(self, plan):
        return self._request("plan", {**plan, "mode": "real"})

    def adapters(self):
        return self._request("adapters")

    def catalogue(self, fragrance_id=None):
        return self._request("catalogue", query={"id": fragrance_id} if fragrance_id else None)

    def readiness(self, mode="real"):
        return self._request("readiness", query={"mode": mode})

    def save_scan(self, scan_id, saved=True, mode="real"):
        return self._request("bookmark", {"mode": mode, "scan_id": scan_id, "saved": saved})

    def connect_sensor(self, adapter_id="bme688", **config):
        return self._request("connect", {"mode": "real", "adapter_id": adapter_id, "config": config})

    def disconnect(self):
        return self._request("disconnect", {})

    def start_scan(self, metadata, mode="real"):
        return self._request("start", {**metadata, "mode": mode})

    def start_capture(self, metadata, duration_s=10):
        return self._request("capture", {**metadata, "mode": "real", "duration_s": duration_s})

    def next_phase(self, scan_id, mode="real"):
        return self._request("phase", {"scan_id": scan_id, "mode": mode})

    def finish_scan(self, scan_id, mode="real", abort=False):
        return self._request("abort" if abort else "finish", {"scan_id": scan_id, "mode": mode})

    def get_scan(self, scan_id, mode="real"):
        return self._request("scan", query={"id": scan_id, "mode": mode})

    def train(self, heldout_group, mode="real", profile_key=None):
        return self._request("train", {"heldout_group": heldout_group, "mode": mode, "profile_key": profile_key})

    def predict(self, scan_id, mode="real"):
        return self._request("predict", {"scan_id": scan_id, "mode": mode})

    def load_demo(self):
        return self._request("seed", {"mode": "simulation"})
