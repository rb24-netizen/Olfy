"""OpenAPI description for the stable local v1 interface."""

from .contracts import UNITS


def openapi():
    reading = {key: {"type": "number", "description": f"Unit: {unit}"} for key, unit in UNITS.items()}
    reading["gas_ohm"].update(minimum=0, exclusiveMinimum=True)
    reading.update(schema_version={"type": "integer", "enum": [1]},
                   source_sequence={"type": "integer", "minimum": 0},
                   extra_channels={"type": "object", "additionalProperties": {"type": "number"}})
    packet = {**reading, "type": {"type": "string", "enum": ["olfy.sample"]},
              "device_id": {"type": "string"}, "profile": {"type": "string"},
              "mode": {"type": "string", "enum": ["real", "simulation"]},
              "units": {"type": "object", "additionalProperties": {"type": "string"}}}
    mode = {"type": "string", "enum": ["simulation", "real"], "default": "simulation"}
    fields = {key: {"type": "string", "maxLength": 120} for key in
              ("fragrance_id", "label", "group_id", "bottle_id", "sample_id", "device_id", "substrate", "dose", "notes")}
    fields["fragrance_id"]["description"] = "Optional reference catalogue ID. Real known reference scans only; the server fills the canonical label. Not accepted for simulation or quick captures."
    fields.update(mode=mode, kind={"type": "string", "enum": ["known", "unknown", "blank"], "default": "known"},
                  drydown_min={"type": "number", "minimum": 0, "maximum": 10080}, warmup_ack={"type": "boolean"})
    fields["notes"]["maxLength"] = 1000
    schemas = {
        "Error": {"type": "object", "required": ["error", "code"], "properties": {"error": {"type": "string"}, "code": {"type": "string"}}},
        "Reading": {"type": "object", "required": ["gas_ohm", "schema_version"], "properties": reading},
        "FirmwarePacket": {"type": "object", "required": ["type", "schema_version", "device_id", "profile", "gas_ohm", "source_sequence"], "properties": packet},
        "StartScan": {"type": "object", "required": ["group_id"], "anyOf": [{"required": ["label"]}, {"required": ["fragrance_id"]}], "properties": fields},
        "StartCapture": {"type": "object", "required": ["mode", "label", "group_id", "bottle_id", "warmup_ack"], "properties": {**fields, "mode": {"type": "string", "enum": ["real"]}, "duration_s": {"type": "number", "minimum": 5, "maximum": 60, "default": 10}}},
        "ScanCommand": {"type": "object", "required": ["mode", "scan_id"], "properties": {"mode": mode, "scan_id": {"type": "string"}}},
        "Connect": {"type": "object", "required": ["mode"], "properties": {"mode": {"type": "string", "enum": ["real"]}, "adapter_id": {"type": "string", "default": "bme688"}, "config": {"type": "object"}}},
        "Train": {"type": "object", "required": ["heldout_group"], "properties": {"mode": mode, "heldout_group": {"type": "string"}, "profile_key": {"type": "string", "nullable": True, "description": "Optional compatible sensor cohort from readiness."}}},
        "Bookmark": {"type": "object", "required": ["scan_id"], "properties": {"mode": mode, "scan_id": {"type": "string"}, "saved": {"type": "boolean", "default": True}}},
        "Predict": {"type": "object", "required": ["scan_id"], "properties": {"mode": mode, "scan_id": {"type": "string"}}},
        "Plan": {"type": "object", "required": ["fragrance_ids", "substrate", "dose", "drydown_min", "start_date"],
                 "additionalProperties": False, "properties": {
                     "mode": mode, "fragrance_ids": {"type": "array", "minItems": 2, "maxItems": 5, "uniqueItems": True, "items": {"type": "string"}},
                     "substrate": {"type": "string", "minLength": 1, "maxLength": 120},
                     "dose": {"type": "string", "minLength": 1, "maxLength": 120},
                     "drydown_min": {"type": "number", "minimum": 0, "maximum": 10080},
                     "include_unknown_control": {"type": "boolean", "default": False, "description": "Add an unfamiliar perfume control each day; without this, unfamiliar-perfume rejection remains untested."},
                     "start_date": {"type": "string", "format": "date"}}},
        "Practice": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["simulation"]}}},
    }
    paths = {}
    gets = {"state": "Get workspace, model and token for writes", "status": "Get connection and current recording status", "adapters": "List adapters, serial ports and USB bridges", "catalogue": "Get sourced reference identities, measurement progress and sensor definitions", "catalogue/export": "Download the committed reference catalogue SQLite database", "scan": "Get a recorded scan", "export": "Download raw CSV", "schema": "Get this OpenAPI document"}
    gets.update({"catalogue/samples": "Get the raw sensor samples behind an indexed perfume fingerprint",
                 "readiness": "Get compatible sensor cohorts, per-label collection coverage and candidate test days",
                 "backup": "Download a complete data backup when no scan is active",
                 "health": "Get software capabilities and connection status; not proof of hardware accuracy"})
    gets.update({"model-runs": "List preserved training runs and evaluations", "model-run": "Get one immutable model and its dataset digest"})
    gets.update({"setup": "Check local software, storage and optional drivers without connecting a sensor",
                 "plan": "Get the saved experiment plan and proposed sample rows; not measurements",
                 "plan/export": "Download the planned collection checklist CSV"})
    for endpoint, description in gets.items():
        operation = {"operationId": "get_" + endpoint.replace("/", "_"), "summary": description,
                     "responses": {"200": {"description": "Success"}, "400": {"description": "Invalid request"}}}
        if endpoint in ("state", "scan", "export", "readiness", "model-runs", "model-run"):
            operation["parameters"] = [{"in": "query", "name": "mode", "schema": mode}]
        if endpoint in ("scan", "catalogue/samples", "model-run"):
            operation.setdefault("parameters", [])
            operation["parameters"].append({"in": "query", "name": "id", "required": True, "schema": {"type": "string"}})
        if endpoint == "catalogue":
            operation["parameters"] = [{"in": "query", "name": "id", "description": "Optional fragrance_id to include its recorded fingerprints.", "schema": {"type": "string"}}]
        if endpoint == "catalogue/export":
            operation["responses"]["200"]["content"] = {"application/vnd.sqlite3": {"schema": {"type": "string", "format": "binary"}}}
        if endpoint == "backup":
            operation["responses"]["200"]["content"] = {"application/zip": {"schema": {"type": "string", "format": "binary"}}}
        if endpoint in ("export", "plan/export"):
            operation["responses"]["200"]["content"] = {"text/csv": {"schema": {"type": "string"}}}
        paths[f"/api/v1/{endpoint}"] = {"get": operation}
    posts = {"connect": ("Connect and validate the first reading", "Connect"),
             "disconnect": ("Disconnect when no recording is active", None),
             "start": ("Start baseline recording", "StartScan"),
             "capture": ("Capture raw real-sensor readings for 10 seconds by default, then save automatically; not a reference scan or perfume identification", "StartCapture"),
             "phase": ("Advance the specified scan to its next phase", "ScanCommand"),
             "finish": ("Finish the specified scan", "ScanCommand"),
             "abort": ("Abort the specified scan and preserve readings", "ScanCommand"),
             "train": ("Train using a held-out collection group", "Train"),
             "bookmark": ("Save or remove a completed recording from the durable collection", "Bookmark"),
             "predict": ("Predict an unseen completed scan", "Predict"),
             "seed": ("Create synthetic examples in simulation only", None),
             "practice": ("Exercise the full software pipeline in a disposable generated dataset; existing recordings and models are untouched", "Practice"),
             "plan": ("Save the experiment plan; no sensor readings are created", "Plan")}
    for endpoint, (description, schema) in posts.items():
        body = {"$ref": f"#/components/schemas/{schema}"} if schema else {"type": "object", "properties": {"mode": mode}}
        paths[f"/api/v1/{endpoint}"] = {"post": {"operationId": f"post_{endpoint}", "summary": description,
            "security": [{"LocalToken": []}], "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
            "responses": {"200": {"description": "Success"}, "400": {"description": "Invalid request or unavailable sensor"}, "403": {"description": "Invalid token or origin"}}}}
    return {"openapi": "3.0.3", "info": {"title": "Olfy local integration API", "version": "1.4.0",
             "description": "Local, single-user research API. Fetch /api/v1/state to obtain csrf_token for writes. Browser apps on another origin need an explicit --allow-origin. Scores are provisional; synthetic data does not prove perfume recognition."},
            "servers": [{"url": "/"}], "paths": paths,
            "components": {"schemas": schemas, "securitySchemes": {"LocalToken": {"type": "apiKey", "in": "header", "name": "X-Olfy-Token"}}}}
