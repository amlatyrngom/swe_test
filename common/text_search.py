import sqlite3, sqlite_vss
from threading import Lock
import typing as t
from common.language_model import LANGUAGE_MODEL
import struct
from semantic_text_splitter import TextSplitter, MarkdownSplitter
import json
import os
import zlib
import re, string

EXACT_ONLY_PATTERNS = ["test", "example"]

def serialize(vector: t.List[float]) -> bytes:
    """Serialize a vector to a byte string."""
    return struct.pack(f"{len(vector)}f", *vector)


def hash_str(s: str, l: int) -> int:
    """Hash a string."""
    k = zlib.adler32(s.encode())
    return k % l


def exact_only(elems) -> bool:
    """Check if the filename is an exact match only."""
    for elem in elems:
        for pattern in EXACT_ONLY_PATTERNS:
            if pattern in elem:
                return True
    return False

class TextSearch:
    """Perform text + embedding search."""

    def __init__(self):
        """Initialize the database connection and create the necessary tables."""
        # Get the configuration.
        config = LANGUAGE_MODEL.config
        working_stage = config["working_stage"]
        llm = LANGUAGE_MODEL.llm
        # Make db directory.
        db_dir = f"{working_stage}/text_search_{llm.value}"
        os.makedirs(db_dir, exist_ok=True)
        # Create the databases.
        parallelism = 8
        self.db_locks = [Lock() for _ in range(parallelism)]
        db_files = [f"{db_dir}/text_search_{i}.db" for i in range(parallelism)]
        with open("configs/schemas/text_search.sql", "r") as f:
            schema = f.read()
        self.dbs = []
        for db_file in db_files:
            print(f"Opening {db_file}")
            db = sqlite3.connect(db_file, check_same_thread=False)
            db.enable_load_extension(True)
            sqlite_vss.load(db)
            cur = db.cursor()
            cur.executescript(schema)
            db.commit()
            self.dbs.append(db)
        text_split_length = config["text_split_length"]
        overlap = text_split_length // 8
        self.splitter = TextSplitter(capacity=text_split_length, overlap=overlap)
        self.subsystem = "text_search"



    def db_idx(self, instance_id):
        return hash_str(instance_id, len(self.dbs))

    def _get_db(self, instance_id):
        idx = self.db_idx(instance_id)
        return self.dbs[idx], self.db_locks[idx]
        
    

    def insert_into_db(self, instance_id, filename, elem_name, parent_name, elem_type, display_level, content):
        """Insert an element into the database."""
        content_embeddings = []
        is_exact_only = exact_only([filename, elem_name]) or display_level == "full"
        for split_idx, split_content in self.splitter.chunk_indices(content):
            if is_exact_only:
                embedding = []
            else:
                cache_key = f"{self.subsystem}_{instance_id}_{filename}_{parent_name}_{elem_name}_{elem_type}_{display_level}_{split_idx}"
                embedding = LANGUAGE_MODEL.embed(split_content, cache_key=cache_key)
            content_embeddings.append((split_idx, split_content, embedding))
        insert_stmt = f"""
            INSERT INTO content_table
            (instance_id, filename, elem_name, parent_name, elem_type, display_level, split_idx, content, embedding)
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """.strip()
        embedding_stmt = f"INSERT INTO vss_search_table (rowid, embedding) VALUES (?, ?)"
        fts_stmt = f"INSERT INTO fts_search_table (rowid, filename, content) VALUES (?, ?, ?)"
        db, db_lock = self._get_db(instance_id)
        with db_lock:
            try:
                cur = db.cursor()
                for split_idx, split_content, content_embedding in content_embeddings:
                    cur.execute(
                        insert_stmt,
                        (instance_id, filename, elem_name, parent_name, elem_type, display_level, split_idx, split_content, json.dumps(content_embedding))
                    )
                    rowid = cur.fetchone()[0]
                    print(f"Rowid: {rowid}")
                    if not is_exact_only:
                        cur.execute(embedding_stmt, (rowid, serialize(content_embedding)))
                    cur.execute(fts_stmt, (rowid, filename, split_content))
                db.commit()
            except sqlite3.IntegrityError:
                # Duplicate entry. Skip.
                pass

    
    def cleanup(self, instance_id):
        """Cleanup entries for a given instance."""
        vss_delete = f"""
            DELETE FROM vss_search_table WHERE rowid IN (SELECT id FROM content_table WHERE instance_id = ?)
        """.strip()
        fts_delete = f"""
            DELETE FROM fts_search_table WHERE rowid IN (SELECT id FROM content_table WHERE instance_id = ?)
        """.strip()
        delete_stmt = f"""
            DELETE FROM content_table WHERE instance_id = ?
        """.strip()
        db, db_lock = self._get_db(instance_id)
        with db_lock:
            cur = db.cursor()
            cur.execute(vss_delete, (instance_id,))
            cur.execute(fts_delete, (instance_id,))
            cur.execute(delete_stmt, (instance_id,))
            db.commit()

    def _make_elem_type_expr(self, elem_type):
        """Create an expression to filter for element types."""
        if elem_type == "code":
            code_expr = "AND elem_type NOT IN ('readme', 'other') AND filename NOT LIKE '%tests%'"
        elif elem_type is not None:
            if isinstance(elem_type, list):
                elem_types = ", ".join([f"'{et}'" for et in elem_type])
                code_expr = f"AND elem_type IN ({elem_types})"
            else:
                code_expr = f"AND elem_type = '{elem_type}'"
        else:
            code_expr = ""
        return code_expr
    
    def _make_dir_expr(self, in_dirs):
        """Create an expression to filter for directories."""
        if in_dirs is None:
            return ""
        if isinstance(in_dirs, list):
            terms = [f"filename LIKE '{d}%'" for d in in_dirs]
            terms = " OR ".join(terms)
            dir_expr = f"AND ({terms})"
        else:
            dir_expr = f"AND filename LIKE '{in_dirs}%'"
        return dir_expr
    
    def _dedup_results(self, results, num_results, dedup_by_file=False):
        """Deduplicate the results."""
        idxs = []
        seen = set()
        for i, r in enumerate(results):
            if dedup_by_file:
                key = (r["filename"])
            else:
                key = (r["filename"], r["elem_name"], r["parent_name"], r["elem_type"], r["split_idx"])
            if key not in seen:
                seen.add(key)
                idxs.append(i)
        return [results[i] for i in idxs][:num_results]
        
    def approximate_search(self, instance_id: str, query: str, num_results=5, cache_key=None, elem_type=None, in_dirs=None, dedup_by_file=True):
        """Perform an approximate search."""
        embedding = LANGUAGE_MODEL.embed(query.strip(), cache_key=cache_key)
        elem_type_expr = self._make_elem_type_expr(elem_type)
        dir_expr = self._make_dir_expr(in_dirs)

        get_elems = f"""
            WITH matching_ids(match_id, distance) AS (
                SELECT rowid, vss_distance_l1(embedding, ?) AS l1_distance FROM vss_search_table
                WHERE rowid IN (SELECT id FROM content_table WHERE instance_id = ? {elem_type_expr} {dir_expr})
                ORDER BY l1_distance
                LIMIT {3*num_results}
            )
            SELECT filename, elem_name, parent_name, elem_type, split_idx, content, distance FROM content_table, matching_ids WHERE id = match_id
            ORDER BY distance
        """.strip()
        print(get_elems)
        db, db_lock = self._get_db(instance_id)
        with db_lock:
            cur = db.cursor()
            cur.execute(get_elems, (serialize(embedding), instance_id))
            results = cur.fetchall()
        results = [
            {"filename": r[0], "elem_name": r[1], "parent_name": r[2], "elem_type": r[3], "split_idx": r[4], "content": r[5], "distance": r[6]}
            for r in results
        ]
        return self._dedup_results(results, num_results, dedup_by_file=dedup_by_file)
        return results

    def _escape_fts_query(self, query: str):
        # Replace punctuation with spaces.
        query = query.translate(str.maketrans(string.punctuation, " " * len(string.punctuation)))
        return query


    def exact_search(self, instance_id, query, num_results=5, elem_type=None, in_dirs=None, dedup=True):
        """Perform an exact search."""
        query = self._escape_fts_query(query)
        print(f"Query: {query}")
        elem_type_expr = self._make_elem_type_expr(elem_type)
        dir_expr = self._make_dir_expr(in_dirs)
        get_elems = f"""
            WITH matching_ids(match_id, distance) AS (
                SELECT rowid, bm25(fts_search_table) AS distance FROM fts_search_table
                WHERE rowid IN (SELECT id FROM content_table WHERE instance_id = ? {elem_type_expr} {dir_expr})
                AND fts_search_table MATCH ?
                ORDER BY distance
                LIMIT {3*num_results}
            )
            SELECT filename, elem_name, parent_name, elem_type, split_idx, content, distance FROM content_table, matching_ids WHERE id = match_id
        """.strip()
        print(get_elems)
        db, db_lock = self._get_db(instance_id)
        with db_lock:
            try:
                cur = db.cursor()
                cur.execute(get_elems, (instance_id, query))
                results = cur.fetchall()
            except sqlite3.OperationalError as e:
                is_fts5 = "fts5" in str(e)
                if is_fts5:
                    print(f"FTS5 not supported. Falling back to approximate search: {e}")
                    results = []
                else:
                    raise e
        results = [
            {"filename": r[0], "elem_name": r[1], "parent_name": r[2], "elem_type": r[3], "split_idx": r[4], "content": r[5], "distance": r[6]}
            for r in results
        ]
        if dedup:
            return self._dedup_results(results, num_results)
        return results


TEXT_SEARCH = TextSearch()