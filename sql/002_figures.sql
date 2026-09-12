CREATE TABLE figures (
    figure_id   SERIAL PRIMARY KEY,
    bank        TEXT NOT NULL,
    year        INT  NOT NULL,
    metric      TEXT NOT NULL,
    value       NUMERIC NOT NULL,
    unit        TEXT NOT NULL,
    doc_id      INT REFERENCES documents,
    page_no     INT,
    source      TEXT NOT NULL,
    UNIQUE (bank, year, metric, source)
);
