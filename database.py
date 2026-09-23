"""データベース（SQLite）まわりの処理をまとめたファイル。

データはアプリと同じフォルダの tagclip.db という1つのファイルに保存されます。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "tagclip.db"

# 設定の初期値
DEFAULT_SETTINGS = {
    "target_domains": "",   # 対象ドメイン（改行区切りで複数可）
    "tag_selector": "",     # タグ要素を指定するCSSセレクタ
    "fetch_interval": "3",  # 複数URLを取得するときの間隔（秒）
    "use_browser": "0",     # 1ならJavaScriptを実行してから取得する
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending / ok / error
    error_message TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,                    -- 登録日時
    fetched_at    TEXT                              -- 最後に取得した日時
);
CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at);
CREATE INDEX IF NOT EXISTS idx_articles_status  ON articles(status);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS article_tags (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,          -- ページ上での並び順
    PRIMARY KEY (article_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags(tag_id);
"""

PER_PAGE = 50


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value)
            )


# ---------------------------------------------------------------- 設定

def get_settings():
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({r["key"]: r["value"] for r in rows})
    return settings


def save_settings(values):
    with connect() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


# ---------------------------------------------------------------- 記事

def url_exists(url):
    with connect() as conn:
        return conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone() is not None


def add_article(url):
    """記事を「取得待ち」として登録し、IDを返す。"""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO articles(url, created_at) VALUES (?, ?)", (url, now_str())
        )
        return cur.lastrowid


def get_article(article_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if row is None:
            return None
        article = dict(row)
        article["tags"] = _tags_for(conn, [article_id]).get(article_id, [])
    return article


def pending_ids():
    with connect() as conn:
        rows = conn.execute("SELECT id FROM articles WHERE status = 'pending' ORDER BY id").fetchall()
    return [r["id"] for r in rows]


def mark_pending(article_ids):
    if not article_ids:
        return
    with connect() as conn:
        conn.executemany(
            "UPDATE articles SET status = 'pending', error_message = '' WHERE id = ?",
            [(i,) for i in article_ids],
        )


def error_ids():
    with connect() as conn:
        rows = conn.execute("SELECT id FROM articles WHERE status = 'error' ORDER BY id").fetchall()
    return [r["id"] for r in rows]


def save_fetch_result(article_id, title, tags, error_message):
    """取得結果を保存する。error_message が空なら成功扱い。"""
    status = "error" if error_message else "ok"
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not exists:  # 取得中に削除された
            return
        conn.execute(
            "UPDATE articles SET title = ?, status = ?, error_message = ?, fetched_at = ? WHERE id = ?",
            (title, status, error_message, now_str(), article_id),
        )
        _replace_tags(conn, article_id, tags)


def update_article(article_id, title, tags):
    """手動編集の保存。タグが1件以上あればエラー状態も解除する。"""
    with connect() as conn:
        conn.execute("UPDATE articles SET title = ? WHERE id = ?", (title, article_id))
        if tags:
            conn.execute(
                "UPDATE articles SET status = 'ok', error_message = '' "
                "WHERE id = ? AND status = 'error'",
                (article_id,),
            )
        _replace_tags(conn, article_id, tags)


def delete_article(article_id):
    with connect() as conn:
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        _delete_unused_tags(conn)


def _replace_tags(conn, article_id, tags):
    conn.execute("DELETE FROM article_tags WHERE article_id = ?", (article_id,))
    for position, name in enumerate(tags):
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO article_tags(article_id, tag_id, position) VALUES (?, ?, ?)",
            (article_id, tag_id, position),
        )
    _delete_unused_tags(conn)


def _delete_unused_tags(conn):
    conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM article_tags)")


def _tags_for(conn, article_ids):
    """記事IDのリスト → {記事ID: [タグ名, ...]}"""
    result = {}
    if not article_ids:
        return result
    placeholders = ",".join("?" * len(article_ids))
    rows = conn.execute(
        f"""SELECT at.article_id, t.name FROM article_tags at
            JOIN tags t ON t.id = at.tag_id
            WHERE at.article_id IN ({placeholders})
            ORDER BY at.article_id, at.position""",
        article_ids,
    ).fetchall()
    for r in rows:
        result.setdefault(r["article_id"], []).append(r["name"])
    return result


# ---------------------------------------------------------------- 一覧・検索

def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_articles(tags=(), mode="and", keyword="", status="", sort="new", page=1):
    """条件に合う記事を1ページ分と、全体の件数を返す。"""
    where, params = [], []

    if tags:
        placeholders = ",".join("?" * len(tags))
        if mode == "or":
            where.append(
                f"""a.id IN (SELECT at.article_id FROM article_tags at
                    JOIN tags t ON t.id = at.tag_id WHERE t.name IN ({placeholders}))"""
            )
            params.extend(tags)
        else:  # AND：選んだタグをすべて持つ記事
            where.append(
                f"""a.id IN (SELECT at.article_id FROM article_tags at
                    JOIN tags t ON t.id = at.tag_id WHERE t.name IN ({placeholders})
                    GROUP BY at.article_id HAVING COUNT(DISTINCT at.tag_id) = ?)"""
            )
            params.extend(tags)
            params.append(len(tags))

    # スペース区切りのキーワードはすべて含むもの（AND）を探す
    for word in keyword.split():
        where.append("a.title LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(word)}%")

    if status in ("ok", "error", "pending"):
        where.append("a.status = ?")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_sql = "a.created_at ASC, a.id ASC" if sort == "old" else "a.created_at DESC, a.id DESC"

    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM articles a {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT a.* FROM articles a {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            params + [PER_PAGE, (page - 1) * PER_PAGE],
        ).fetchall()
        articles = [dict(r) for r in rows]
        tag_map = _tags_for(conn, [a["id"] for a in articles])
    for a in articles:
        a["tags"] = tag_map.get(a["id"], [])
    return articles, total


def tag_counts(order="count"):
    """タグ一覧（件数付き）。"""
    order_sql = "t.name COLLATE NOCASE" if order == "name" else "cnt DESC, t.name COLLATE NOCASE"
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT t.name, COUNT(*) AS cnt FROM tags t
                JOIN article_tags at ON at.tag_id = t.id
                GROUP BY t.id ORDER BY {order_sql}"""
        ).fetchall()
    return [(r["name"], r["cnt"]) for r in rows]


def status_counts():
    with connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS cnt FROM articles GROUP BY status").fetchall()
    counts = {"ok": 0, "error": 0, "pending": 0}
    counts.update({r["status"]: r["cnt"] for r in rows})
    counts["all"] = sum(counts[k] for k in ("ok", "error", "pending"))
    return counts


def all_articles_for_export():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM articles ORDER BY id").fetchall()
        articles = [dict(r) for r in rows]
        tag_rows = conn.execute(
            """SELECT at.article_id, t.name FROM article_tags at
               JOIN tags t ON t.id = at.tag_id ORDER BY at.article_id, at.position"""
        ).fetchall()
    tag_map = {}
    for r in tag_rows:
        tag_map.setdefault(r["article_id"], []).append(r["name"])
    for a in articles:
        a["tags"] = tag_map.get(a["id"], [])
    return articles
