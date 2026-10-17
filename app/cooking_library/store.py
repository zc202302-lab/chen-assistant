"""Separate SQLite catalogue; never opens the assistant business database."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3


def root():
    from app import config
    return Path(os.environ.get('COOKING_LIBRARY_DIR', str(config.DATA_DIR / 'cooking-library'))).expanduser()


@contextmanager
def database():
    folder = root()
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / 'catalogue.sqlite3', timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY,title TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN (\'ebooks\',\'magazines\')),object_key TEXT UNIQUE NOT NULL,sha256 TEXT UNIQUE NOT NULL,pages INTEGER NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS pages(book_id INTEGER REFERENCES books(id),page INTEGER,text TEXT NOT NULL,method TEXT NOT NULL,PRIMARY KEY(book_id,page))')
        conn.execute('CREATE TABLE IF NOT EXISTS book_contents(book_id INTEGER REFERENCES books(id),position INTEGER,title TEXT NOT NULL,page INTEGER NOT NULL,level INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(book_id,position))')
        # Trigram handles Chinese without splitting recipes into individual characters.
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS page_search USING fts5(text,book_id UNINDEXED,page UNINDEXED,tokenize='trigram')")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def search(conn, query):
    query = query.strip()
    if not query:
        return []
    if len(query) > 100:
        raise ValueError('搜索词最多100字')
    if len(query) < 3:
        return conn.execute('SELECT b.title,b.id,p.page,p.text FROM pages p JOIN books b ON b.id=p.book_id WHERE instr(p.text,?)>0 ORDER BY b.id,p.page LIMIT 101', (query,)).fetchall()
    return conn.execute('SELECT b.title,b.id,p.page,p.text FROM page_search s JOIN books b ON b.id=s.book_id JOIN pages p ON p.book_id=s.book_id AND p.page=s.page WHERE page_search MATCH ? ORDER BY rank LIMIT 101', ('"' + query.replace('"', '""') + '"',)).fetchall()
