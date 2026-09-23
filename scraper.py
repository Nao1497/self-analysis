"""ページの取得とタグの抽出を行うファイル。"""
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 TagClip/1.0 (personal use)"
)
TIMEOUT = 20          # 1ページの取得を待つ最大秒数
MAX_TAG_LENGTH = 100  # 長すぎる文字列はタグとみなさない

# 相手サイトへのアクセスが連続しないよう、前回アクセスからの間隔を管理する
_throttle_lock = threading.Lock()
_last_access = 0.0


class FetchError(Exception):
    """ページ取得やタグ抽出に失敗したときのエラー。"""


# ---------------------------------------------------------------- URL・ドメイン

def normalize_url(text):
    """入力されたURLを整える。URLとして不正なら None。"""
    text = text.strip()
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    # ホスト名は小文字にそろえ、ページ内リンク（#以降）は取り除く
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def parse_domains(text):
    """設定画面のドメイン入力（改行・カンマ・空白区切り）をリストにする。"""
    domains = []
    for item in text.replace(",", "\n").split():
        item = item.strip().lower()
        if "://" in item:  # URLごと貼り付けられた場合はホスト名だけ取り出す
            item = urlsplit(item).hostname or ""
        item = item.strip("/").removeprefix("www.")
        if item and item not in domains:
            domains.append(item)
    return domains


def is_target_domain(url, domains):
    """URLのホストが対象ドメイン（またはそのサブドメイン）ならTrue。"""
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


# ---------------------------------------------------------------- 取得・抽出

def _wait_politely(interval):
    global _last_access
    with _throttle_lock:
        wait = _last_access + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_access = time.monotonic()


def fetch_html(url, interval=0):
    _wait_politely(interval)
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        raise FetchError(f"タイムアウトしました（{TIMEOUT}秒以内に応答がありません）")
    except requests.exceptions.ConnectionError:
        raise FetchError("接続できませんでした（URLの誤り、またはネットワークの問題）")
    except requests.exceptions.RequestException as e:
        raise FetchError(f"取得に失敗しました：{e}")
    if res.status_code >= 400:
        raise FetchError(f"ページを取得できませんでした（HTTPステータス {res.status_code}）")
    content_type = res.headers.get("Content-Type", "")
    if content_type and "html" not in content_type.lower():
        raise FetchError(f"HTMLページではありません（{content_type}）")
    return res.content  # 文字コードの判定はBeautifulSoupに任せる


def extract(html, selector):
    """HTMLからタイトルとタグ一覧を取り出す。戻り値：(タイトル, タグのリスト, 一致した要素数)"""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text() if soup.title else ""
    if not title.strip():
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"]
        elif soup.h1:
            title = soup.h1.get_text()
    title = " ".join(title.split())

    try:
        elements = soup.select(selector)
    except Exception as e:  # セレクタの書き方が間違っている
        raise FetchError(f"CSSセレクタの書き方に誤りがあります：{e}")

    texts = []
    for el in elements:
        if el.name == "meta":
            # <meta name="keywords" content="a,b,c"> のような要素にも対応
            texts.extend((el.get("content") or "").replace("、", ",").split(","))
        else:
            texts.append(el.get_text(" "))
    return title, clean_tags(texts), len(elements)


def clean_tags(texts):
    """前後の空白や先頭の # を取り除き、重複（大文字小文字の違いを含む）をなくす。"""
    tags, seen = [], set()
    for text in texts:
        name = " ".join(text.split()).lstrip("#＃").strip()
        if not name or len(name) > MAX_TAG_LENGTH:
            continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            tags.append(name)
    return tags


def fetch_tags(url, selector, interval=0):
    """URLを取得してタグを抽出する。戻り値：(タイトル, タグのリスト, 一致した要素数)"""
    if not selector.strip():
        raise FetchError("タグのCSSセレクタが設定されていません（設定画面で設定してください）")
    html = fetch_html(url, interval)
    return extract(html, selector)
