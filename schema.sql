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
    content_fingerprint TEXT NOT NULL DEFAULT '',
    duplicate_of_recipe_id TEXT REFERENCES recipes(site_recipe_id) ON DELETE SET NULL,
    duplicate_similarity REAL,
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

CREATE TABLE IF NOT EXISTS text_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    vocabulary_size INTEGER NOT NULL DEFAULT 0,
    cluster_count INTEGER NOT NULL DEFAULT 0,
    clustering_method TEXT NOT NULL DEFAULT 'legacy',
    silhouette_score REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES text_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    vector_json TEXT NOT NULL,
    norm REAL NOT NULL,
    cluster_label INTEGER NOT NULL DEFAULT 0,
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0,
    z REAL NOT NULL DEFAULT 0,
    top_terms_json TEXT NOT NULL,
    UNIQUE(run_id, recipe_id)
);

CREATE TABLE IF NOT EXISTS document_term_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES text_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    tf REAL NOT NULL,
    idf REAL NOT NULL,
    tfidf REAL NOT NULL,
    UNIQUE(run_id, recipe_id, term)
);

CREATE TABLE IF NOT EXISTS document_similarities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES text_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    neighbor_recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank > 0),
    cosine_similarity REAL NOT NULL,
    UNIQUE(run_id, recipe_id, neighbor_recipe_id)
);

CREATE TABLE IF NOT EXISTS embedding_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    vocabulary_size INTEGER NOT NULL DEFAULT 0,
    dimension INTEGER NOT NULL DEFAULT 0,
    window_size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS word_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES embedding_runs(id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    top_contexts_json TEXT NOT NULL,
    UNIQUE(run_id, term)
);

CREATE TABLE IF NOT EXISTS document_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES embedding_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    vector_json TEXT NOT NULL,
    norm REAL NOT NULL,
    top_tokens_json TEXT NOT NULL,
    UNIQUE(run_id, recipe_id)
);

CREATE TABLE IF NOT EXISTS embedding_similarities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES embedding_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    neighbor_recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank > 0),
    cosine_similarity REAL NOT NULL,
    UNIQUE(run_id, recipe_id, neighbor_recipe_id)
);

CREATE TABLE IF NOT EXISTS classification_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    target_field TEXT NOT NULL,
    classification_type TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    train_count INTEGER NOT NULL DEFAULT 0,
    test_count INTEGER NOT NULL DEFAULT 0,
    class_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    accuracy REAL,
    macro_precision REAL,
    macro_recall REAL,
    macro_f1 REAL,
    model_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classification_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES classification_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    split TEXT NOT NULL CHECK (split IN ('train', 'test')),
    actual_label TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    probabilities_json TEXT NOT NULL,
    UNIQUE(run_id, recipe_id)
);

CREATE TABLE IF NOT EXISTS classification_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES classification_runs(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    precision REAL NOT NULL,
    recall REAL NOT NULL,
    f1 REAL NOT NULL,
    support INTEGER NOT NULL,
    UNIQUE(run_id, label)
);

CREATE TABLE IF NOT EXISTS linguistic_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    sentence_count INTEGER NOT NULL DEFAULT 0,
    dependency_count INTEGER NOT NULL DEFAULT 0,
    sentiment_count INTEGER NOT NULL DEFAULT 0,
    entity_count INTEGER NOT NULL DEFAULT 0,
    relation_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS syntactic_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES linguistic_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    sentence_index INTEGER NOT NULL,
    token_index INTEGER NOT NULL,
    token TEXT NOT NULL,
    lemma TEXT NOT NULL,
    head_index INTEGER,
    relation TEXT NOT NULL,
    source_text TEXT NOT NULL,
    UNIQUE(run_id, recipe_id, sentence_index, token_index)
);

CREATE TABLE IF NOT EXISTS sentiment_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES linguistic_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    polarity TEXT NOT NULL,
    score REAL NOT NULL,
    subjectivity REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    aspects_json TEXT NOT NULL,
    UNIQUE(run_id, recipe_id, field_name, position)
);

CREATE TABLE IF NOT EXISTS named_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES linguistic_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    entity_text TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    bio_tag TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    UNIQUE(run_id, recipe_id, field_name, position, start_char, end_char, entity_type)
);

CREATE TABLE IF NOT EXISTS semantic_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES linguistic_analysis_runs(id) ON DELETE CASCADE,
    recipe_id TEXT NOT NULL REFERENCES recipes(site_recipe_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    source_field TEXT NOT NULL,
    source_position INTEGER NOT NULL,
    confidence REAL NOT NULL,
    extraction_method TEXT NOT NULL,
    UNIQUE(run_id, recipe_id, subject, relation, object, source_field, source_position)
);

CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating_value);
CREATE INDEX IF NOT EXISTS idx_recipes_difficulty ON recipes(difficulty);
CREATE INDEX IF NOT EXISTS idx_recipes_cost ON recipes(cost_label);
CREATE INDEX IF NOT EXISTS idx_listings_recipe ON category_listings(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_categories_category ON recipe_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_text_preparations_recipe ON text_preparations(recipe_id);
CREATE INDEX IF NOT EXISTS idx_text_preparations_duplicate ON text_preparations(duplicate_key);
CREATE INDEX IF NOT EXISTS idx_text_preparations_near_duplicate ON text_preparations(near_duplicate_key);
CREATE INDEX IF NOT EXISTS idx_document_vectors_run ON document_vectors(run_id);
CREATE INDEX IF NOT EXISTS idx_document_vectors_cluster ON document_vectors(run_id, cluster_label);
CREATE INDEX IF NOT EXISTS idx_document_term_weights_run ON document_term_weights(run_id, term);
CREATE INDEX IF NOT EXISTS idx_document_similarities_run ON document_similarities(run_id, recipe_id, rank);
CREATE INDEX IF NOT EXISTS idx_word_embeddings_run ON word_embeddings(run_id, term);
CREATE INDEX IF NOT EXISTS idx_document_embeddings_run ON document_embeddings(run_id);
CREATE INDEX IF NOT EXISTS idx_embedding_similarities_run ON embedding_similarities(run_id, recipe_id, rank);
CREATE INDEX IF NOT EXISTS idx_classification_predictions_run ON classification_predictions(run_id, split);
CREATE INDEX IF NOT EXISTS idx_classification_metrics_run ON classification_metrics(run_id, label);
CREATE INDEX IF NOT EXISTS idx_syntactic_dependencies_run ON syntactic_dependencies(run_id, recipe_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_analyses_run ON sentiment_analyses(run_id, recipe_id);
CREATE INDEX IF NOT EXISTS idx_named_entities_run ON named_entities(run_id, recipe_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_semantic_relations_run ON semantic_relations(run_id, recipe_id, relation);
