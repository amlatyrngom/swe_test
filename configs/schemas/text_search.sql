CREATE VIRTUAL TABLE IF NOT EXISTS vss_search_table USING vss0 (
    -- Hidden rowid column corresponding to rowid in code_elements table.
    embedding(1024),
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_search_table USING fts5 (
    filename, -- The filename of the code element.
    content, -- The code of the element.
);


CREATE TABLE IF NOT EXISTS content_table (
    id INTEGER PRIMARY KEY,
    instance_id TEXT,
    filename TEXT,
    elem_name TEXT,
    parent_name TEXT, -- empty string if top-level, otherwise the name of the parent element.
    elem_type TEXT, -- module, function, class, method, readme.
    display_level TEXT,
    split_idx INTEGER,
    content TEXT,
    content_with_lines TEXT,
    embedding TEXT
)