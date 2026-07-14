-- Sample schema + data so the UI has something to explore out of the box.
-- Loaded automatically by the local Postgres container (docker-compose).

CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id       SERIAL PRIMARY KEY,
    email    TEXT UNIQUE NOT NULL,
    role     TEXT NOT NULL DEFAULT 'member'
);

CREATE TABLE IF NOT EXISTS spans (
    id          BIGSERIAL PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id),
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    duration_ms INTEGER,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO projects (name) VALUES
    ('phoenix'), ('temporal'), ('unified-dash')
ON CONFLICT DO NOTHING;

INSERT INTO users (email, role) VALUES
    ('vmr.rajaraman@gmail.com', 'admin'),
    ('ops@zensar.com', 'member'),
    ('dev@zensar.com', 'member')
ON CONFLICT DO NOTHING;

INSERT INTO spans (project_id, name, status, duration_ms)
SELECT
    (i % 3) + 1,
    'span-' || i,
    (ARRAY['OK', 'ERROR', 'TIMEOUT'])[(i % 3) + 1],
    (i * 37) % 5000
FROM generate_series(1, 250) AS s(i);
