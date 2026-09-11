PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_url TEXT NOT NULL,
    max_pages INTEGER NOT NULL CHECK (max_pages > 0),
    user_agent TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    listing_count INTEGER NOT NULL DEFAULT 0,
    recipe_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    site_category_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS recipes (
    site_recipe_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    rating_value REAL CHECK (rating_value IS NULL OR (rating_value >= 0 AND rating_value <= 5)),
    ratings_count INTEGER,
    prep_time_minutes INTEGER,
    prep_time_raw TEXT,
    difficulty TEXT,
    cost_label TEXT,
    servings INTEGER,
    description TEXT,
    search_text TEXT NOT NULL DEFAULT '',
    retrieved_at TEXT NOT NULL,
    parser_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    raw_text TEXT NOT NULL,
    UNIQUE(recipe_id, position)
);

CREATE TABLE IF NOT EXISTS utensils (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    name TEXT NOT NULL,
    UNIQUE(recipe_id, position)
);

CREATE TABLE IF NOT EXISTS preparation_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    raw_text TEXT NOT NULL,
    UNIQUE(recipe_id, position)
);

CREATE TABLE IF NOT EXISTS recipe_categories (
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    category_id TEXT NOT NULL REFERENCES categories(site_category_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'related',
    PRIMARY KEY (recipe_id, category_id, relation_type)
);

CREATE TABLE IF NOT EXISTS category_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    category_id TEXT NOT NULL REFERENCES categories(site_category_id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL,
    recipe_url TEXT NOT NULL,
    listed_title TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    position INTEGER NOT NULL CHECK (position > 0),
    UNIQUE(run_id, category_id, page_number, recipe_id)
);

CREATE TABLE IF NOT EXISTS text_preparations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    raw_text TEXT NOT NULL,
    clean_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    tokens_json TEXT NOT NULL,
    content_tokens_json TEXT NOT NULL,
    stemmed_tokens_json TEXT NOT NULL,
    lemma_tokens_json TEXT NOT NULL,
    duplicate_key TEXT NOT NULL,
    near_duplicate_key TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    transformations_json TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    UNIQUE(recipe_id, field_name, position)
);

CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating_value);
CREATE INDEX IF NOT EXISTS idx_recipes_difficulty ON recipes(difficulty);
CREATE INDEX IF NOT EXISTS idx_recipes_cost ON recipes(cost_label);
CREATE INDEX IF NOT EXISTS idx_listings_recipe ON category_listings(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_categories_category ON recipe_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_text_preparations_recipe ON text_preparations(recipe_id);
CREATE INDEX IF NOT EXISTS idx_text_preparations_duplicate ON text_preparations(duplicate_key);
CREATE INDEX IF NOT EXISTS idx_text_preparations_near_duplicate ON text_preparations(near_duplicate_key);
