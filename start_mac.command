#!/bin/bash
# TagClip 起動スクリプト（Mac用）。ダブルクリックで起動します。
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "[1/3] 仮想環境を作成しています（初回のみ）..."
    if ! python3 -m venv .venv; then
        echo "エラー：Python が見つかりません。README.md を見て Python をインストールしてください。"
        read -r -p "Enterキーで閉じます"
        exit 1
    fi
fi

echo "[2/3] 必要なパッケージを確認しています..."
if ! .venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt; then
    echo "エラー：パッケージのインストールに失敗しました。インターネット接続を確認してください。"
    read -r -p "Enterキーで閉じます"
    exit 1
fi

if [ ! -f ".venv/browser_ready.txt" ]; then
    echo "[3/3] JavaScript実行用のブラウザをダウンロードしています（初回のみ・数分かかります）..."
    if .venv/bin/python -m playwright install chromium; then
        echo ok > .venv/browser_ready.txt
    else
        echo "注意：ブラウザのダウンロードに失敗しました。Google Chrome が入っていればそれを使います。"
    fi
fi

.venv/bin/python app.py
