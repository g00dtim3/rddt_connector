-- V1.1+ : Dataset Library (voir docs/01-spec-fonctionnelle.md §3).
-- `datasets` ne gardait aucun lien vers la configuration qui l'a produite,
-- utilisable uniquement en mémoire de session (via app.py). Nécessaire pour
-- que les actions Rafraîchir / Étendre fonctionnent depuis un nouvel écran,
-- après redémarrage de l'app ou dans une autre session.

ALTER TABLE datasets ADD COLUMN IF NOT EXISTS config_id BIGINT REFERENCES acquisition_configs(id);

CREATE INDEX IF NOT EXISTS idx_datasets_config_id ON datasets(config_id);
