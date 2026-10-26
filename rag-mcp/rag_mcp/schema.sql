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

-- synthetic 플래그를 없애기 전에 만든 DB용.
ALTER TABLE adcheck_rag.documents DROP COLUMN IF EXISTS synthetic;

-- 초기 데이터 규모에서는 정확한 코사인 검색으로 충분하고, 필터를 건 top-k도 정확하게 유지된다.
-- 근사(ANN) 인덱스는 데이터 크기와 검색 시간을 재 보고 필요할 때만 추가한다.
