CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  role TEXT NOT NULL CHECK (role IN ('operator','analyst','manager','admin')),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE categories (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,        -- roads, garbage, lighting, transport...
  name_ru TEXT NOT NULL,
  base_weight REAL DEFAULT 1.0      -- вес категории для приоритета
);

CREATE TABLE districts (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  geom GEOMETRY(MultiPolygon, 4326)  -- если PostGIS; иначе убрать
);

CREATE TABLE import_batches (
  id SERIAL PRIMARY KEY,
  filename TEXT, source TEXT,        -- open_data / synthetic / manual
  rows_total INT, rows_ok INT, rows_failed INT,
  uploaded_by INT REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE clusters (
  id SERIAL PRIMARY KEY,
  category_id INT REFERENCES categories(id),
  district_id INT REFERENCES districts(id),
  centroid_lat DOUBLE PRECISION, centroid_lon DOUBLE PRECISION,
  appeals_count INT DEFAULT 1,
  first_seen TIMESTAMPTZ, last_seen TIMESTAMPTZ,
  status TEXT DEFAULT 'open'         -- open / in_progress / closed
);

CREATE TABLE appeals (
  id BIGSERIAL PRIMARY KEY,
  batch_id INT REFERENCES import_batches(id),
  external_id TEXT,                  -- номер в исходных данных
  text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  district_id INT REFERENCES districts(id),
  lat DOUBLE PRECISION, lon DOUBLE PRECISION,
  category_id INT REFERENCES categories(id),   -- разметка из источника, если есть
  cluster_id INT REFERENCES clusters(id),
  status TEXT DEFAULT 'new'
);

CREATE TABLE ml_models (
  id SERIAL PRIMARY KEY,
  task TEXT,                         -- classifier / forecast / anomaly
  name TEXT, version TEXT,
  metrics JSONB,                     -- accuracy, macro-F1, MAE...
  trained_at TIMESTAMPTZ
);

CREATE TABLE appeal_predictions (
  id BIGSERIAL PRIMARY KEY,
  appeal_id BIGINT REFERENCES appeals(id),
  model_id INT REFERENCES ml_models(id),
  predicted_category_id INT REFERENCES categories(id),
  confidence REAL,
  urgency REAL                       -- срочность по тексту, 0..1
);

CREATE TABLE priority_scores (
  id BIGSERIAL PRIMARY KEY,
  cluster_id INT REFERENCES clusters(id),
  score REAL NOT NULL,
  factors JSONB NOT NULL,            -- вклад каждого фактора (объяснение)
  calculated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE aggregates_daily (
  day DATE, category_id INT, district_id INT, cnt INT,
  PRIMARY KEY (day, category_id, district_id)
);

CREATE TABLE forecasts (
  id BIGSERIAL PRIMARY KEY,
  model_id INT REFERENCES ml_models(id),
  category_id INT, district_id INT,
  target_date DATE, value REAL, lower REAL, upper REAL
);

CREATE TABLE anomalies (
  id BIGSERIAL PRIMARY KEY,
  category_id INT, district_id INT, day DATE,
  observed INT, expected REAL, score REAL
);

CREATE TABLE reports (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  kind TEXT, params JSONB, file_path TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  action TEXT, entity TEXT, entity_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON appeals (created_at);
CREATE INDEX ON appeals (category_id, district_id);