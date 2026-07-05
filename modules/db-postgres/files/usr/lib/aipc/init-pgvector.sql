CREATE EXTENSION IF NOT EXISTS vector;

-- rag-ingest's four watchers all write here. One shared table, source
-- column tells them apart (desktop/code/browser-firefox/browser-chrome/
-- screen-audio) — simplest schema that works for v1; split into
-- per-source tables only if a source needs a materially different shape.
CREATE TABLE IF NOT EXISTS rag_chunks (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1024) NOT NULL,  -- bge-m3 dense output dim
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, path, chunk_index)
);

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS rag_chunks_source_idx ON rag_chunks (source);
