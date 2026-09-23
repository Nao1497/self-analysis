#!/bin/bash
# TagClip 起動スクリプト（Mac用）。ダブルクリックで起動します。
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "[1/2] 仮想環境を作成しています（初回のみ）..."
    if ! python3 -m venv .venv; then
        echo "エラー：Python が見つかりません。README.md を見て Python をインストールしてください。"
        read -r -p "Enterキーで閉じます"
        exit 1
    fi
fi

echo "[2/2] 必要なパッケージを確認しています..."
if ! .venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt; then
    echo "エラー：パッケージのインストールに失敗しました。インターネット接続を確認してください。"
    read -r -p "Enterキーで閉じます"
    exit 1
fi

.venv/bin/python app.py
