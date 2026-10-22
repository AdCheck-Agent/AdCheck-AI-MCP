CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS adcheck_rag;

CREATE TABLE IF NOT EXISTS adcheck_rag.profile (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    embedding_profile text NOT NULL
);

CREATE TABLE IF NOT EXISTS adcheck_rag.documents (
    scope text NOT NULL,
    document_id text NOT NULL,
    company_id text,
    corpus text NOT NULL CHECK (corpus IN ('social', 'corporate')),
    document_type text NOT NULL,
    title text NOT NULL,
    version text NOT NULL,
    synthetic boolean NOT NULL,
    checksum text NOT NULL,
    revision integer NOT NULL DEFAULT 1,
    metadata jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, document_id),
    CHECK ((corpus = 'social' AND company_id IS NULL AND scope = 'social') OR
           (corpus = 'corporate' AND company_id IS NOT NULL AND scope = 'company:' || company_id))
);

CREATE TABLE IF NOT EXISTS adcheck_rag.chunks (
    scope text NOT NULL,
    document_id text NOT NULL,
    chunk_id text NOT NULL,
    section text NOT NULL,
    content text NOT NULL,
    metadata jsonb NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY (scope, document_id, chunk_id),
    FOREIGN KEY (scope, document_id)
        REFERENCES adcheck_rag.documents(scope, document_id) ON DELETE CASCADE
);

-- Exact cosine search is sufficient for the initial corpus and keeps filtered top-k exact.
-- Add a measured ANN index only when corpus size and query timings justify it.
