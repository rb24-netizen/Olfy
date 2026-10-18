"""A transparent baseline with whole-day evaluation and heuristic rejection."""

from collections import Counter
import hashlib
import json
import uuid

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_NAMES, FEATURE_VERSION, REFERENCE_PROTOCOL, extract, scan_profile
from .storage import now

THRESHOLDS = {"score": .60, "margin": .15, "radius_multiplier": 1.5,
              "minimum_log_response": .02, "baseline_noise_multiplier": 3.0}


def infer(model, scan):
    if scan.get("mode") != model["mode"]:
        raise ValueError("A simulation model cannot classify real scans, or vice versa.")
    if model["mode"] == "real" and not model.get("signal_profile_key"):
        raise ValueError("This older real model lacks the sensor configuration checks. Retrain it before comparing new scans.")
    if scan.get("profile") != model["profile"]:
        raise ValueError("Heater profile differs from the training profile. Train a separate model.")
    if model["feature_version"] != FEATURE_VERSION:
        raise ValueError("Model features are outdated. Retrain this workspace.")
    if model.get("signal_profile_key") and scan_profile(scan)[0] != model["signal_profile_key"]:
        raise ValueError("Sensor settings, channel units or sampling rate differ from training. Choose a compatible model.")
    if scan.get("acquisition_protocol", REFERENCE_PROTOCOL) != model.get("acquisition_protocol", REFERENCE_PROTOCOL):
        raise ValueError("Capture protocol differs from the reference model.")
    vector, qc = extract(scan)
    z = (vector - np.array(model["mean"])) / np.array(model["scale"])
    logits = np.array(model["coef"]) @ z + np.array(model["intercept"])
    if len(model["classes"]) == 2:
        logits = np.array([0., float(logits[0])])
    probabilities = np.exp(logits - np.max(logits))
    probabilities /= probabilities.sum()
    order = np.argsort(probabilities)[::-1]
    winner = int(order[0])
    distance = float(np.linalg.norm(z - np.array(model["centers"])[winner]))
    ratio = distance / model["radii"][winner]
    score = float(probabilities[winner])
    margin = score - float(probabilities[order[1]])
    reasons = []
    limits = model["thresholds"]
    if qc["max_abs_exposure_log"] < max(limits["minimum_log_response"],
                                          limits["baseline_noise_multiplier"] * qc["baseline_log_std"]):
        reasons.append("No sufficiently large response above the clean-air baseline noise.")
    if score < limits["score"]:
        reasons.append("Model score is below the acceptance threshold.")
    if margin < limits["margin"]:
        reasons.append("The two leading candidates are too close.")
    if ratio > limits["radius_multiplier"]:
        reasons.append("The response is far from this candidate's training responses.")
    for phase, duration in qc["phase_durations_s"].items():
        reference = model["phase_durations_s"][phase]
        if not .75 * reference <= duration <= 1.25 * reference:
            reasons.append(f"{phase.capitalize()} duration differs by more than 25% from training.")
    warnings = list(qc["warnings"])
    if scan.get("device_id") not in model["device_ids"]:
        warnings.append("This device was absent from training. Cross-device accuracy is untested.")
        reasons.append("Device differs from the training devices.")
    context = model.get("sampling_context", {})
    for field in ("substrate", "dose"):
        value = str(scan.get(field, "")).strip().casefold()
        if context.get(field) and value not in context[field]:
            reasons.append(f"{field.capitalize()} differs from the recorded training conditions.")
    if context.get("drydown_min"):
        lower, upper = context["drydown_min"]
        if not lower <= float(scan.get("drydown_min", 0)) <= upper:
            reasons.append("Drydown is outside the measured training range.")
    identities = model.get("class_fragrances", {})
    return {"decision": "unknown" if reasons else "match",
            "label": None if reasons else model["classes"][winner],
            "fragrance_id": None if reasons else identities.get(model["classes"][winner]),
            "top_candidates": [{"label": model["classes"][int(i)],
                                "fragrance_id": identities.get(model["classes"][int(i)]),
                                "score": float(probabilities[i])} for i in order[:3]],
            "distance_ratio": ratio, "margin": margin, "reasons": reasons,
            "warnings": warnings, "qc": qc, "mode": model["mode"],
            "score_note": "Model scores are uncalibrated. Rejection rules are unvalidated heuristics."}


def predict(model, scan):
    if scan["id"] in model["train_scan_ids"]:
        raise ValueError("This scan was used for training. Choose a held-out or newly recorded scan.")
    return infer(model, scan)


def train(store, mode, heldout_group, signal_profile_key=None):
    summaries = [s for s in store.list(mode) if s["status"] == "complete"]
    scans = [store.get(mode, s["id"]) for s in summaries]
    if signal_profile_key:
        scans = [s for s in scans if scan_profile(s)[0] == signal_profile_key]
    train_scans = [s for s in scans if s["group_id"] != heldout_group and s["kind"] == "known"]
    test_scans = [s for s in scans if s["group_id"] == heldout_group]
    if not test_scans:
        raise ValueError("Choose a collection day containing complete test scans.")
    labels = sorted({s["label"] for s in train_scans})
    if len(labels) < 2:
        raise ValueError("Collect at least two perfume labels on days other than the test day.")
    for label in labels:
        scans = [s for s in train_scans if s["label"] == label]
        if len(scans) < 3 or len({s["group_id"] for s in scans}) < 2:
            raise ValueError(f"{label}: need at least 3 training scans across at least 2 training days.")
    test_known = {s["label"] for s in test_scans if s["kind"] == "known"}
    if test_known != set(labels):
        raise ValueError("The test day must contain the same known labels as training. "
                         "Mark unfamiliar test perfumes as unknown controls.")
    train_samples = {s["sample_id"] for s in train_scans}
    if train_samples & {s["sample_id"] for s in test_scans}:
        raise ValueError("A sample ID appears in both training and testing. Use fresh independent samples.")
    profiles = {s["profile"] for s in train_scans + test_scans}
    if len(profiles) != 1:
        raise ValueError("Mixed heater profiles. Use one profile per workspace/model.")
    signatures = {scan_profile(s)[0] for s in train_scans + test_scans}
    if len(signatures) != 1:
        raise ValueError("Mixed sensor settings, units or sample rates. Select one compatible sensor configuration before training.")
    if any(s.get("acquisition_protocol", REFERENCE_PROTOCOL) != REFERENCE_PROTOCOL for s in train_scans + test_scans):
        raise ValueError("Only the baseline/exposure/recovery protocol is supported by this model.")
    identities = {}
    for label in labels:
        ids = {s.get("fragrance_id") or None for s in train_scans + test_scans if s["kind"] == "known" and s["label"] == label}
        if len(ids) > 1:
            raise ValueError("One label is linked to inconsistent catalogue identities. Relabel samples before training.")
        identities[label] = next(iter(ids))
    vectors, durations = [], []
    for scan in train_scans:
        vector, qc = extract(scan)
        vectors.append(vector)
        durations.append(qc["phase_durations_s"])
    x = np.array(vectors)
    y = [s["label"] for s in train_scans]
    scaler = StandardScaler().fit(x)
    z = scaler.transform(x)
    classifier = LogisticRegression(C=1, max_iter=2000, random_state=0).fit(z, y)
    centers, radii = [], []
    for label in classifier.classes_:
        members = z[np.array(y) == label]
        center = members.mean(axis=0)
        centers.append(center.tolist())
        # Leave-one-out distances use training exposures only, never the test day.
        loo_centers = (members.sum(axis=0) - members) / (len(members) - 1)
        distances = np.linalg.norm(members - loo_centers, axis=1)
        radii.append(max(.5, float(np.quantile(distances, .95))))
    protocol = {phase: float(np.median([d[phase] for d in durations]))
                for phase in ("exposure", "recovery")}
    if any(not .75 * protocol[p] <= d[p] <= 1.25 * protocol[p]
           for d in durations for p in protocol):
        raise ValueError("Training phase durations differ too much. Collect with consistent timings.")
    payload = {"model_id": uuid.uuid4().hex, "created_at": now(), "mode": mode,
               "data_digest": hashlib.sha256(json.dumps(sorted(train_scans + test_scans, key=lambda s: s["id"]),
                                                        sort_keys=True, allow_nan=False).encode()).hexdigest(),
               "feature_version": FEATURE_VERSION, "features": FEATURE_NAMES,
               "signal_profile_key": next(iter(signatures)),
               "signal_definition": scan_profile(train_scans[0])[1],
               "acquisition_protocol": REFERENCE_PROTOCOL,
               "class_fragrances": identities,
               "sampling_context": {"substrate": sorted({str(s.get("substrate", "")).strip().casefold() for s in train_scans}),
                                    "dose": sorted({str(s.get("dose", "")).strip().casefold() for s in train_scans}),
                                    "drydown_min": [min(float(s.get("drydown_min", 0)) for s in train_scans),
                                                     max(float(s.get("drydown_min", 0)) for s in train_scans)]},
               "profile": next(iter(profiles)), "classes": classifier.classes_.tolist(),
               "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
               "coef": classifier.coef_.tolist(), "intercept": classifier.intercept_.tolist(),
               "centers": centers, "radii": radii, "thresholds": dict(THRESHOLDS),
               "phase_durations_s": protocol,
               "device_ids": sorted({s["device_id"] for s in train_scans}),
               "train_scan_ids": [s["id"] for s in train_scans],
               "train_groups": sorted({s["group_id"] for s in train_scans}),
               "heldout_group": heldout_group,
               "limitations": ["One fixed heater setting and one gas-resistance channel.",
                               "Scores and unknown thresholds are not calibrated.",
                               "A held-out day does not establish accuracy on skin or unseen bottles.",
                               "Synthetic performance does not establish perfume recognition."]}
    rows = []
    matrix_labels = labels + ["Unknown / blank"]
    matrix = [[0] * len(matrix_labels) for _ in matrix_labels]
    for scan in test_scans:
        result = infer(payload, scan)
        truth = scan["label"] if scan["kind"] == "known" else "Unknown / blank"
        decision = result["label"] if result["decision"] == "match" else "Unknown / blank"
        matrix[matrix_labels.index(truth)][matrix_labels.index(decision)] += 1
        rows.append({"scan_id": scan["id"], "truth": truth, "prediction": decision,
                     "correct": truth == decision, "kind": scan["kind"],
                     "reasons": result["reasons"]})
    known = [r for r in rows if r["kind"] == "known"]
    accepted = [r for r in known if r["prediction"] != "Unknown / blank"]
    unknown = [r for r in rows if r["kind"] != "known"]
    report = {"mode": mode, "heldout_group": heldout_group, "train_count": len(train_scans),
              "test_count": len(rows), "known_count": len(known),
              "known_identification_rate": sum(r["correct"] for r in known) / len(known),
              "known_coverage": len(accepted) / len(known),
              "accepted_accuracy": (sum(r["correct"] for r in accepted) / len(accepted)
                                    if accepted else None),
              "unknown_count": len(unknown),
              "unknown_rejection_rate": (sum(r["correct"] for r in unknown) / len(unknown)
                                         if unknown else None),
              "training_counts": dict(Counter(y)), "matrix_labels": matrix_labels,
              "confusion_matrix": matrix, "results": rows,
              "evaluation_note": ("Synthetic software test only." if mode == "simulation" else
                                  "One held-out collection day. Requires independent replication.")}
    payload["report"] = report
    store.save_model(mode, payload)
    return payload
