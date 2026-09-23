"""TagClip（タグ・クリップ）本体。

起動方法：  python app.py
停止方法：  この画面（黒いウィンドウ／ターミナル）で Ctrl + C
"""
import csv
import io
import os
import re
import socket
import sqlite3
import threading
import webbrowser
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, url_for

import database
import scraper
from worker import worker

PORT = int(os.environ.get("TAGCLIP_PORT", "8000"))
STATUS_LABELS = {"ok": "取得済み", "error": "エラー", "pending": "取得待ち"}

app = Flask(__name__)
app.secret_key = "tagclip-local-only"  # 画面上のお知らせ表示（flash）に使うだけ


@app.context_processor
def common_values():
    return {"counts": database.status_counts(), "status_labels": STATUS_LABELS}


def safe_next(default="/"):
    """編集後に戻る先。アプリ内のページだけを許可する。"""
    target = request.values.get("next", "")
    if target.startswith("/") and not target.startswith("//"):
        return target
    return default


# ---------------------------------------------------------------- 一覧・検索

def read_filters():
    tags = []
    for t in request.args.getlist("tag"):
        t = t.strip()
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    return {
        "tags": tags,
        "mode": "or" if request.args.get("mode") == "or" else "and",
        "q": request.args.get("q", "").strip(),
        "status": request.args.get("status", ""),
        "sort": "old" if request.args.get("sort") == "old" else "new",
        "page": page,
    }


def list_url(filters, **changes):
    """現在の検索条件の一部だけを変えた一覧ページのURLを作る。"""
    f = dict(filters, **changes)
    params = [("tag", t) for t in f["tags"]]
    if f["tags"] and f["mode"] == "or":
        params.append(("mode", "or"))
    for key in ("q", "status"):
        if f[key]:
            params.append((key, f[key]))
    if f["sort"] == "old":
        params.append(("sort", "old"))
    if f["page"] > 1:
        params.append(("page", f["page"]))
    return "/" + ("?" + urlencode(params) if params else "")


@app.route("/")
def index():
    filters = read_filters()
    articles, total = database.search_articles(
        tags=filters["tags"], mode=filters["mode"], keyword=filters["q"],
        status=filters["status"], sort=filters["sort"], page=filters["page"],
    )
    pages = max(1, -(-total // database.PER_PAGE))
    return render_template(
        "index.html",
        articles=articles, total=total, pages=pages, filters=filters,
        all_tags=database.tag_counts(), list_url=list_url,
    )


@app.route("/tags")
def tags():
    order = "name" if request.args.get("order") == "name" else "count"
    return render_template("tags.html", tags=database.tag_counts(order), order=order)


# ---------------------------------------------------------------- URL登録

URL_IN_TEXT = re.compile(r"https?://\S+")


@app.route("/add", methods=["GET", "POST"])
def add():
    settings = database.get_settings()
    domains = scraper.parse_domains(settings["target_domains"])
    results, text = [], ""

    if request.method == "POST":
        text = request.form.get("urls", "")
        if not domains:
            flash("先に「設定」画面で対象ドメインを設定してください。", "error")
            return render_template("add.html", domains=domains, results=[], text=text)

        seen, new_ids = set(), []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            found = URL_IN_TEXT.search(raw)  # 前後に余計な文字があってもURL部分だけ使う
            url = scraper.normalize_url(found.group(0)) if found else None
            if not url:
                results.append({"url": raw, "ok": False, "reason": "URLの形式ではありません"})
            elif not scraper.is_target_domain(url, domains):
                results.append({"url": url, "ok": False, "reason": "対象ドメイン外のため登録しません"})
            elif url in seen:
                results.append({"url": url, "ok": False, "reason": "入力の中で同じURLが重複しています"})
            elif database.url_exists(url):
                results.append({"url": url, "ok": False, "reason": "登録済みのURLです"})
            else:
                try:
                    new_ids.append(database.add_article(url))
                    results.append({"url": url, "ok": True, "reason": "登録しました（タグ取得待ち）"})
                except sqlite3.IntegrityError:
                    results.append({"url": url, "ok": False, "reason": "登録済みのURLです"})
            seen.add(url)

        worker.enqueue(new_ids)
        if new_ids:
            text = ""  # 登録できたときは入力欄を空にする
        if not results:
            flash("URLが入力されていません。", "error")

    added = sum(1 for r in results if r["ok"])
    return render_template(
        "add.html", domains=domains, results=results, text=text,
        added=added, skipped=len(results) - added,
        selector_missing=not settings["tag_selector"].strip(),
    )


# ---------------------------------------------------------------- 設定

def selector_error(selector):
    try:
        BeautifulSoup("", "html.parser").select(selector)
        return None
    except Exception as e:
        return str(e)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    current = database.get_settings()
    if request.method == "POST":
        domains = scraper.parse_domains(request.form.get("target_domains", ""))
        selector = request.form.get("tag_selector", "").strip()
        interval = request.form.get("fetch_interval", "3").strip()
        use_browser = "1" if request.form.get("use_browser") else "0"

        errors = []
        if not domains:
            errors.append("対象ドメインを1つ以上入力してください。")
        if not selector:
            errors.append("タグのCSSセレクタを入力してください。")
        elif selector_error(selector):
            errors.append(f"CSSセレクタの書き方に誤りがあります：{selector_error(selector)}")
        try:
            interval_num = float(interval)
            if not 1 <= interval_num <= 60:
                raise ValueError
        except ValueError:
            errors.append("取得間隔は1〜60の数字（秒）で入力してください。")

        if errors:
            for e in errors:
                flash(e, "error")
            current = {"target_domains": request.form.get("target_domains", ""),
                       "tag_selector": selector, "fetch_interval": interval,
                       "use_browser": use_browser}
        else:
            database.save_settings({"target_domains": "\n".join(domains),
                                    "tag_selector": selector, "fetch_interval": interval,
                                    "use_browser": use_browser})
            flash("設定を保存しました。", "success")
            return redirect(url_for("settings"))

    return render_template("settings.html", settings=current, test=None,
                           test_url="", test_selector=current["tag_selector"],
                           test_use_browser=current["use_browser"] == "1")


@app.route("/settings/test", methods=["POST"])
def settings_test():
    """タグ抽出のテスト。結果を表示するだけで保存はしない。"""
    current = database.get_settings()
    test_url = request.form.get("test_url", "").strip()
    test_selector = request.form.get("test_selector", "").strip()
    test_use_browser = bool(request.form.get("test_use_browser"))
    test = {"url": test_url, "error": None, "title": "", "tags": [], "matched": 0, "warning": None, "hint": None}

    url = scraper.normalize_url(test_url)
    if not url:
        test["error"] = "URLの形式が正しくありません（http:// または https:// で始まるURLを入力してください）"
    else:
        domains = scraper.parse_domains(current["target_domains"])
        if domains and not scraper.is_target_domain(url, domains):
            test["warning"] = "このURLは対象ドメイン外です（テストは実行しますが、登録はできません）"
        try:
            test["title"], test["tags"], test["matched"] = scraper.fetch_tags(
                url, test_selector, interval=1, use_browser=test_use_browser)
            if not test["tags"]:
                test["hint"] = scraper.empty_tags_hint(test["matched"], test_use_browser)
        except scraper.FetchError as e:
            test["error"] = str(e)

    return render_template("settings.html", settings=current, test=test,
                           test_url=test_url, test_selector=test_selector,
                           test_use_browser=test_use_browser)


# ---------------------------------------------------------------- 記事の編集・削除・再取得

@app.route("/article/<int:article_id>", methods=["GET", "POST"])
def article(article_id):
    item = database.get_article(article_id)
    if item is None:
        abort(404)
    if request.method == "POST":
        title = " ".join(request.form.get("title", "").split())
        tags = scraper.clean_tags(request.form.get("tags", "").splitlines())
        database.update_article(article_id, title, tags)
        flash("保存しました。", "success")
        return redirect(safe_next(url_for("article", article_id=article_id)))
    # 「一覧に戻る」の行き先（検索条件を保ったまま戻れるようにする）
    back = request.args.get("next") or ""
    if not back and request.referrer:
        ref = urlsplit(request.referrer)
        back = ref.path + ("?" + ref.query if ref.query else "")
    if not back.startswith("/") or back.startswith("//") or back.startswith("/article/"):
        back = "/"
    return render_template("article.html", article=item, back=back)


@app.route("/article/<int:article_id>/delete", methods=["POST"])
def delete(article_id):
    database.delete_article(article_id)
    flash("記事を削除しました。", "success")
    return redirect(safe_next())


@app.route("/article/<int:article_id>/refetch", methods=["POST"])
def refetch(article_id):
    if database.get_article(article_id) is None:
        abort(404)
    database.mark_pending([article_id])
    worker.enqueue([article_id])
    flash("再取得を予約しました。しばらくしてから再読み込みしてください。", "success")
    return redirect(safe_next())


@app.route("/refetch-errors", methods=["POST"])
def refetch_errors():
    ids = database.error_ids()
    database.mark_pending(ids)
    worker.enqueue(ids)
    flash(f"エラーの記事 {len(ids)} 件の再取得を予約しました。", "success")
    return redirect(safe_next())


# ---------------------------------------------------------------- CSV・状態

@app.route("/export.csv")
def export_csv():
    buf = io.StringIO()
    buf.write("﻿")  # Excelで文字化けしないようにする印（BOM）
    writer = csv.writer(buf)
    writer.writerow(["ID", "URL", "タイトル", "タグ", "状態", "エラー内容", "登録日時", "最終取得日時"])
    for a in database.all_articles_for_export():
        writer.writerow([
            a["id"], a["url"], a["title"], " | ".join(a["tags"]),
            STATUS_LABELS.get(a["status"], a["status"]), a["error_message"],
            a["created_at"], a["fetched_at"] or "",
        ])
    filename = f"tagclip_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/status")
def api_status():
    counts = database.status_counts()
    return jsonify(pending=counts["pending"], error=counts["error"], current=worker.current_url)


# ---------------------------------------------------------------- 起動

def lan_ip():
    """同じWi-Fi内の他の機器からアクセスするときのIPアドレスを調べる。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # 実際には通信しない
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def main():
    from waitress import serve

    database.init_db()
    worker.start()

    ip = lan_ip()
    print("=" * 60)
    print(" TagClip を起動しました")
    print(f"  このPCから     : http://localhost:{PORT}")
    if ip:
        print(f"  スマホなどから : http://{ip}:{PORT}")
    print("  停止するには、この画面で Ctrl + C を押してください")
    print("=" * 60, flush=True)

    if os.environ.get("TAGCLIP_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    serve(app, host="0.0.0.0", port=PORT, threads=8)


if __name__ == "__main__":
    main()
