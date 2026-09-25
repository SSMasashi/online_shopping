"""
Amazon vs 楽天 最安振り分け計算（Streamlit アプリの入口）

ローカルで実行:
    uv sync
    uv run streamlit run src/buy_sl.py

必要な Secrets（ローカルは .streamlit/secrets.toml、本番は Streamlit Cloud の Secrets）は
README.md を参照。楽天APIの認証情報は画面にも Google Sheets にも出さない。

計算は shopping.calc、楽天APIは shopping.rakuten、保存は shopping.storage にある。
"""

import streamlit as st

# set_page_config は最初の st 呼び出しでなければならないため、画面の import より先に呼ぶ。
st.set_page_config(page_title="Amazon×楽天 最安振り分け計算", page_icon="🛒", layout="wide")

from shopping.ui import main  # noqa: E402

main()
