-- SpoofNet schema for Postgres with PostGIS and h3-pg (free tier or local).
-- The local SQLite store in service.py uses the same tables without the generated columns.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS h3;
CREATE EXTENSION IF NOT EXISTS h3_postgis CASCADE;

CREATE TABLE IF NOT EXISTS events (
  id          bigserial PRIMARY KEY,
  token       char(24) NOT NULL,              -- unlinkable per day and per res 5 region
  tier        char(1)  NOT NULL CHECK (tier IN ('A','B','C','D')),
  t_start     timestamptz NOT NULL,
  t_end       timestamptz NOT NULL,
  cell        h3index NOT NULL,               -- res 10 on arrival, coarsened to res 8 after one hour
  type        text NOT NULL CHECK (type IN ('jam','spoof','meacon','loss_unknown')),
  score       real NOT NULL CHECK (score BETWEEN 0 AND 1),
  reasons     jsonb NOT NULL DEFAULT '[]',
  obs         jsonb NOT NULL DEFAULT '{}',
  evidence    text NOT NULL CHECK (evidence IN ('replay','real')),
  pos_source  text,
  t_received  timestamptz NOT NULL DEFAULT now(),
  geom        geometry(Point, 4326) GENERATED ALWAYS AS (h3_cell_to_geometry(cell)) STORED,
  UNIQUE (token, t_start, type)
);
CREATE INDEX IF NOT EXISTS events_time ON events (t_start);
CREATE INDEX IF NOT EXISTS events_geom ON events USING gist (geom);

CREATE TABLE IF NOT EXISTS pings (
  token    char(24) NOT NULL,
  cell7    h3index NOT NULL,
  hour     integer NOT NULL,                  -- whole hours since the Unix epoch
  tier     char(1) NOT NULL,
  seconds  integer NOT NULL CHECK (seconds BETWEEN 1 AND 3600),
  PRIMARY KEY (token, cell7, hour)
);
CREATE INDEX IF NOT EXISTS pings_hour ON pings (hour);

CREATE TABLE IF NOT EXISTS incidents (
  id          text PRIMARY KEY,
  type        text NOT NULL,
  confidence  real NOT NULL,
  t_start     timestamptz NOT NULL,
  t_end       timestamptz NOT NULL,
  t_created   timestamptz NOT NULL,
  n_devices   integer NOT NULL,
  weight      real NOT NULL,
  body        jsonb NOT NULL,                 -- cells, source estimate with ellipse, reasons, evidence, adsb
  updated     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incidents_time ON incidents (t_start);

CREATE TABLE IF NOT EXISTS api_keys (key_hash char(64) PRIMARY KEY, tier text NOT NULL, name text);
CREATE TABLE IF NOT EXISTS geofences (
  id bigserial PRIMARY KEY, key_hash char(64) REFERENCES api_keys, name text, cells7 jsonb NOT NULL,
  min_confidence real NOT NULL DEFAULT 0.5, types jsonb NOT NULL, webhook text, secret text);
CREATE TABLE IF NOT EXISTS alerts (
  id bigserial PRIMARY KEY, geofence_id bigint REFERENCES geofences, incident_id text REFERENCES incidents,
  t timestamptz NOT NULL DEFAULT now(), body jsonb NOT NULL, delivered boolean NOT NULL DEFAULT false,
  UNIQUE (geofence_id, incident_id));

-- Retention (DESIGN.md section 9): event detail for 90 days, then aggregates only.
-- Run daily:  DELETE FROM events WHERE t_received < now() - interval '90 days';
--             DELETE FROM pings  WHERE hour < extract(epoch FROM now() - interval '400 days') / 3600;
