CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    doc_id      SERIAL PRIMARY KEY,
    bank        TEXT NOT NULL,
    year        INT  NOT NULL,
    doc_type    TEXT NOT NULL,
    lang        TEXT NOT NULL,
    title       TEXT,
    source_url  TEXT,
    sha256      TEXT UNIQUE NOT NULL,
    n_pages     INT
);

CREATE TABLE pages (
    doc_id   INT REFERENCES documents ON DELETE CASCADE,
    page_no  INT,
    text     TEXT,
    PRIMARY KEY (doc_id, page_no)
);

CREATE TABLE chunks (
    chunk_id     BIGSERIAL PRIMARY KEY,
    doc_id       INT REFERENCES documents ON DELETE CASCADE,
    chunker      TEXT NOT NULL,
    page_start   INT NOT NULL,
    page_end     INT NOT NULL,
    section_path TEXT,
    kind         TEXT NOT NULL,
    content      TEXT NOT NULL,
    n_tokens     INT,
    ts_config    REGCONFIG NOT NULL,
    tsv          TSVECTOR
);
CREATE INDEX chunks_tsv_idx     ON chunks USING GIN (tsv);
CREATE INDEX chunks_chunker_idx ON chunks (chunker);
CREATE INDEX chunks_doc_idx     ON chunks (doc_id);

-- emb_<model> tables are created from Python (fixed vector dimension per model).
