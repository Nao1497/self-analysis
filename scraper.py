"""ページの取得とタグの抽出を行うファイル。"""
import os
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


RENDER_WAIT = 15  # JavaScriptでタグが表示されるのを待つ最大秒数

# タグ（セレクタに一致し、文字が入っている要素）が表示されたらtrueを返すJavaScript
_TAGS_READY_JS = """(sel) => {
  try {
    return Array.from(document.querySelectorAll(sel)).some(
      (e) => ((e.tagName === "META" ? e.content : e.textContent) || "").trim() !== "");
  } catch (err) { return true; }
}"""
_browser_lock = threading.Lock()


def _launch_browser(p):
    """付属のChromium → Edge → Chrome の順に、起動できるブラウザを使う。

    環境変数 TAGCLIP_BROWSER_PATH にブラウザの実行ファイルを指定すると、それを最優先で使う。
    """
    candidates = [{}, {"channel": "msedge"}, {"channel": "chrome"}]
    if os.environ.get("TAGCLIP_BROWSER_PATH"):
        candidates.insert(0, {"executable_path": os.environ["TAGCLIP_BROWSER_PATH"]})
    first_error = None
    for options in candidates:
        try:
            return p.chromium.launch(headless=True, **options)
        except Exception as e:
            first_error = first_error or e
    reason = str(first_error).strip().splitlines()[0] if first_error else ""
    raise FetchError(
        "JavaScript実行用のブラウザを起動できませんでした。"
        "起動ファイルからアプリを起動し直してください（README「困ったときは」参照）"
        + (f"［詳細：{reason[:200]}］" if reason else "")
    )


def fetch_rendered_html(url, selector, interval=0):
    """見えないブラウザでページを開き、JavaScriptの実行後のHTMLを返す。"""
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError:
        raise FetchError("Playwrightが入っていません。起動ファイルからアプリを起動し直してください")

    _wait_politely(interval)
    with _browser_lock:  # ブラウザは1つずつ動かす
        try:
            with sync_playwright() as p:
                browser = _launch_browser(p)
                try:
                    page = browser.new_page(user_agent=USER_AGENT, locale="ja-JP")
                    # 画像・動画・フォントは読み込まない（速くするため）
                    page.route("**/*", lambda route: route.abort()
                               if route.request.resource_type in ("image", "media", "font")
                               else route.continue_())
                    try:
                        res = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT * 1000)
                    except PlaywrightError as e:
                        if "Timeout" in str(e):
                            raise FetchError(f"タイムアウトしました（{TIMEOUT}秒以内に表示されません）")
                        raise FetchError("接続できませんでした（URLの誤り、またはネットワークの問題）")
                    if res is not None and res.status >= 400:
                        raise FetchError(f"ページを取得できませんでした（HTTPステータス {res.status}）")
                    try:
                        page.wait_for_function(_TAGS_READY_JS, arg=selector, timeout=RENDER_WAIT * 1000)
                        page.wait_for_timeout(500)  # タグが続けて追加される場合に備えて少し待つ
                    except PlaywrightError:
                        pass  # 待ってもタグが出なかった → この時点の内容で判定する
                    return page.content()
                finally:
                    browser.close()
        except FetchError:
            raise
        except Exception as e:
            raise FetchError(f"ブラウザでの取得に失敗しました：{e}")


def fetch_tags(url, selector, interval=0, use_browser=False):
    """URLを取得してタグを抽出する。戻り値：(タイトル, タグのリスト, 一致した要素数)

    use_browser=True のときは、JavaScriptを実行した後のページから抽出する。
    """
    if not selector.strip():
        raise FetchError("タグのCSSセレクタが設定されていません（設定画面で設定してください）")
    if use_browser:
        html = fetch_rendered_html(url, selector, interval)
    else:
        html = fetch_html(url, interval)
    return extract(html, selector)


def empty_tags_hint(matched, use_browser):
    """タグが0件だったときの原因の目安。"""
    if use_browser:
        if matched:
            return "セレクタに一致する要素はありましたが、中身が空でした。セレクタが指す場所を確認してください"
        return "セレクタに一致する要素がありませんでした。セレクタが合っているか確認してください"
    if matched:
        return ("セレクタに一致する要素はありましたが、中身が空でした。"
                "タグがJavaScriptで後から表示されるサイトです。設定の「JavaScriptを実行して取得する」をオンにしてください")
    return ("セレクタに一致する要素がありませんでした。セレクタが合っていないか、"
            "タグがJavaScriptで後から表示されるサイトの可能性があります")
