PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS catalogue_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    retailer TEXT NOT NULL,
    market TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fragrances (
    fragrance_id TEXT PRIMARY KEY,
    selection_order INTEGER NOT NULL UNIQUE,
    brand TEXT NOT NULL,
    name TEXT NOT NULL,
    label TEXT NOT NULL UNIQUE,
    concentration_label TEXT,
    concentration_pct REAL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    product_id TEXT NOT NULL,
    product_url TEXT NOT NULL,
    source_display_position INTEGER NOT NULL,
    details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sensor_profiles (
    profile_key TEXT PRIMARY KEY,
    adapter_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    channels_json TEXT NOT NULL,
    settings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_measurements (
    scan_id TEXT PRIMARY KEY,
    fragrance_id TEXT NOT NULL REFERENCES fragrances(fragrance_id),
    measured_at TEXT NOT NULL,
    device_id TEXT NOT NULL,
    profile_key TEXT NOT NULL REFERENCES sensor_profiles(profile_key),
    acquisition_protocol TEXT NOT NULL,
    feature_scheme TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('usable','needs_review')),
    features_json TEXT,
    channel_summary_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    quality_json TEXT NOT NULL,
    sensor_json TEXT NOT NULL,
    raw_database TEXT NOT NULL DEFAULT 'real.sqlite3'
);
CREATE INDEX IF NOT EXISTS reference_fragrance_idx
    ON reference_measurements(fragrance_id, status);
CREATE TABLE IF NOT EXISTS feature_definitions (
    scheme TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    feature_order INTEGER NOT NULL,
    source_channel TEXT NOT NULL,
    unit TEXT NOT NULL,
    calculation TEXT NOT NULL,
    PRIMARY KEY(scheme, feature_name)
);
CREATE TABLE IF NOT EXISTS reference_features (
    scan_id TEXT NOT NULL REFERENCES reference_measurements(scan_id),
    scheme TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY(scan_id, feature_name),
    FOREIGN KEY(scheme, feature_name) REFERENCES feature_definitions(scheme, feature_name)
);
CREATE TABLE IF NOT EXISTS reference_samples (
    scan_id TEXT NOT NULL REFERENCES reference_measurements(scan_id),
    sequence INTEGER NOT NULL,
    elapsed_s REAL NOT NULL,
    phase TEXT NOT NULL,
    gas_ohm REAL,
    temperature_c REAL,
    humidity_pct REAL,
    pressure_hpa REAL,
    heater_c REAL,
    heater_ms REAL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(scan_id, sequence)
);
CREATE INDEX IF NOT EXISTS feature_lookup_idx ON reference_features(scheme,feature_name,value);
CREATE VIEW IF NOT EXISTS perfume_sensor_features AS
    SELECT f.fragrance_id,f.brand,f.name,m.scan_id,m.device_id,m.profile_key,
           p.profile_id,m.acquisition_protocol,v.scheme,v.feature_name,v.value,d.unit
    FROM fragrances f JOIN reference_measurements m USING(fragrance_id)
    JOIN sensor_profiles p USING(profile_key)
    JOIN reference_features v USING(scan_id)
    JOIN feature_definitions d ON d.scheme=v.scheme AND d.feature_name=v.feature_name;
CREATE VIEW IF NOT EXISTS perfume_sensor_samples AS
    SELECT f.fragrance_id,f.brand,f.name,m.device_id,m.profile_key,r.*
    FROM fragrances f JOIN reference_measurements m USING(fragrance_id)
    JOIN reference_samples r USING(scan_id);
CREATE VIEW IF NOT EXISTS catalogue_progress AS
    SELECT f.fragrance_id, f.label,
           COUNT(m.scan_id) AS reference_count,
           COALESCE(SUM(m.status='usable'), 0) AS usable_count,
           CASE WHEN COALESCE(SUM(m.status='usable'), 0)>0 THEN 'measured'
                WHEN COUNT(m.scan_id)>0 THEN 'needs_review'
                ELSE 'pending' END AS measurement_status
    FROM fragrances f LEFT JOIN reference_measurements m USING(fragrance_id)
    GROUP BY f.fragrance_id;
