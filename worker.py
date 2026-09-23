"""登録されたURLを裏側で1件ずつ順番に取得する仕組み。

画面の操作を止めないよう、取得は別スレッドで行います。
相手サイトに負荷をかけないよう、設定した間隔（秒）をあけて1件ずつ処理します。
"""
import queue
import threading
import traceback

import database
import scraper


class FetchWorker:
    def __init__(self):
        self._queue = queue.Queue()
        self._queued = set()          # 同じ記事を二重に並べないための記録
        self._lock = threading.Lock()
        self.current_url = None       # いま取得中のURL（画面表示用）

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        # 前回、取得の途中でアプリを止めた記事があれば続きから処理する
        self.enqueue(database.pending_ids())

    def enqueue(self, article_ids):
        with self._lock:
            for article_id in article_ids:
                if article_id not in self._queued:
                    self._queued.add(article_id)
                    self._queue.put(article_id)

    def _run(self):
        while True:
            article_id = self._queue.get()
            try:
                self._process(article_id)
            except Exception:
                traceback.print_exc()
            finally:
                with self._lock:
                    self._queued.discard(article_id)
                self.current_url = None

    def _process(self, article_id):
        article = database.get_article(article_id)
        if article is None or article["status"] != "pending":
            return  # 削除済み、または処理不要
        self.current_url = article["url"]

        settings = database.get_settings()
        try:
            interval = max(1.0, float(settings["fetch_interval"]))
        except ValueError:
            interval = 3.0

        title, tags, error = article["title"], [], ""
        try:
            title, tags, matched = scraper.fetch_tags(article["url"], settings["tag_selector"], interval)
            if not tags:
                error = (
                    "タグが0件でした（セレクタに一致する要素が"
                    f"{matched}件）。セレクタが合っていないか、"
                    "タグがJavaScriptで後から表示されるサイトの可能性があります"
                )
        except scraper.FetchError as e:
            error = str(e)
        except Exception as e:  # 想定外のエラーも記録して次へ進む
            error = f"予期しないエラー：{e}"
        database.save_fetch_result(article_id, title, tags, error)
        print(f"[取得] {'OK ' if not error else 'NG '} {article['url']}  タグ{len(tags)}件 {error}")


worker = FetchWorker()
