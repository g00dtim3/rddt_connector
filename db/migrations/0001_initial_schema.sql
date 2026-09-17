-- Schéma initial, voir docs/03-modele-donnees.md.
-- Toutes les tables sont créées dès le v1, y compris celles qui ne servent
-- qu'aux renforts v1.1+ (bw_filter_catalog, coverage), pour éviter une
-- migration de schéma plus tard.

CREATE TABLE IF NOT EXISTS bw_projects (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bw_queries (
    id BIGINT PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES bw_projects(id),
    name TEXT NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bw_queries_project_id ON bw_queries(project_id);

-- v1.1+ : catalogue de valeurs de filtres synchronisées depuis Brandwatch.
CREATE TABLE IF NOT EXISTS bw_filter_catalog (
    id BIGSERIAL PRIMARY KEY,
    parameter TEXT NOT NULL,
    native_value TEXT NOT NULL,
    display_value TEXT,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS acquisition_projects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS acquisition_configs (
    id BIGSERIAL PRIMARY KEY,
    acquisition_project_id BIGINT REFERENCES acquisition_projects(id),
    project_id BIGINT NOT NULL REFERENCES bw_projects(id),
    query_id BIGINT NOT NULL REFERENCES bw_queries(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    filters JSONB NOT NULL DEFAULT '[]'::jsonb,
    config_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Couvre les vérifications de couverture (config + fenêtre de dates), voir
-- docs/03-modele-donnees.md section "Index et contraintes".
CREATE INDEX IF NOT EXISTS idx_acquisition_configs_query ON acquisition_configs(query_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_acquisition_configs_hash ON acquisition_configs(config_hash);

CREATE TABLE IF NOT EXISTS volume_checks (
    id BIGSERIAL PRIMARY KEY,
    config_id BIGINT NOT NULL REFERENCES acquisition_configs(id),
    ui_volume INTEGER NOT NULL,
    api_volume INTEGER NOT NULL,
    difference INTEGER NOT NULL,
    difference_pct NUMERIC NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('MATCH', 'WARNING', 'MISMATCH')),
    excluded_recent_window TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_volume_checks_config ON volume_checks(config_id);

CREATE TABLE IF NOT EXISTS acquisition_runs (
    id BIGSERIAL PRIMARY KEY,
    config_id BIGINT NOT NULL REFERENCES acquisition_configs(id),
    status TEXT NOT NULL CHECK (
        status IN ('CREATED', 'VALIDATING', 'READY', 'RUNNING', 'FAILED', 'COMPLETED', 'CANCELLED')
    ),
    expected_volume INTEGER,
    requested_volume INTEGER,
    received_volume INTEGER NOT NULL DEFAULT 0,
    inserted_volume INTEGER NOT NULL DEFAULT 0,
    existing_volume INTEGER NOT NULL DEFAULT 0,
    checkpoint TEXT,
    error_code TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_acquisition_runs_config ON acquisition_runs(config_id);

-- v1.1+ : ce qui est déjà couvert localement pour une config donnée.
CREATE TABLE IF NOT EXISTS coverage (
    id BIGSERIAL PRIMARY KEY,
    config_id BIGINT NOT NULL REFERENCES acquisition_configs(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coverage_config ON coverage(config_id);

CREATE TABLE IF NOT EXISTS reddit_mentions (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    source_native_id TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    full_text TEXT,
    author TEXT,
    url TEXT,
    language TEXT,
    raw_payload JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_native_id)
);

CREATE INDEX IF NOT EXISTS idx_reddit_mentions_published_at ON reddit_mentions(published_at);

CREATE TABLE IF NOT EXISTS datasets (
    id BIGSERIAL PRIMARY KEY,
    acquisition_project_id BIGINT REFERENCES acquisition_projects(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('LOCAL', 'PARTIAL', 'STALE', 'COMPLETE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_mentions (
    dataset_id BIGINT NOT NULL REFERENCES datasets(id),
    mention_id BIGINT NOT NULL REFERENCES reddit_mentions(id),
    PRIMARY KEY (dataset_id, mention_id)
);

CREATE INDEX IF NOT EXISTS idx_dataset_mentions_dataset ON dataset_mentions(dataset_id);
CREATE INDEX IF NOT EXISTS idx_dataset_mentions_mention ON dataset_mentions(mention_id);

CREATE TABLE IF NOT EXISTS exports (
    id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(id),
    file_name TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    requested_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
