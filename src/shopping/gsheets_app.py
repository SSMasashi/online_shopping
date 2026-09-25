"""
Streamlit の Secrets と Google Sheets（保存・読み込み・削除）を画面につなぐ処理。

シートへの読み書きそのものは shopping.storage にある。
ここではキャッシュと session_state の更新を担当する。
"""

import os

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

from shopping.storage import SETTING_DEFAULTS, SheetStorage

# ===========================================================================
# Secrets（優先順位: Streamlit Secrets → 環境変数。値は画面に表示しない）
# ===========================================================================
#
# 優先順位:
#   1. Streamlit Cloud Secrets
#   2. 環境変数
#
# Secretsの内容は画面に表示しない。
#
# ---------------------------------------------------------------------------


def get_secret_or_env(name: str, default: str = "") -> str:
    """
    Streamlit Secretsから値を取得する。

    Streamlit Cloudでは st.secrets を使用する。
    ローカル環境などでSecretsがない場合は環境変数を使用する。

    取得した値を画面には表示しない。
    """

    try:
        value = st.secrets.get(name, None)

        if value is not None:
            return str(value).strip()

    except Exception:
        pass

    return os.environ.get(name, default).strip()


# ===========================================================================
# Google Sheets
# ===========================================================================

# スプレッドシートはIDで開くので、Driveの権限は不要。
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_google_credentials():
    """Streamlit SecretsからGoogleサービスアカウント認証情報を作成する。"""

    try:
        info = dict(st.secrets["gcp_service_account"])
    except Exception as e:
        raise ValueError("gcp_service_accountの設定が正しくありません。") from e

    required = [
        "type",
        "project_id",
        "private_key_id",
        "private_key",
        "client_email",
        "client_id",
        "token_uri",
    ]

    missing = [key for key in required if not str(info.get(key, "")).strip()]

    if missing:
        raise ValueError("gcp_service_accountに必要な項目がありません：" + ", ".join(missing))

    private_key = str(info["private_key"])

    if "BEGIN PRIVATE KEY" not in private_key:
        raise ValueError(
            "gcp_service_accountのprivate_keyが正しくありません。"
            "Google Cloudから発行した秘密鍵を設定してください。"
        )

    try:
        return Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)
    except Exception as e:
        raise ValueError(
            "Googleサービスアカウントの認証に失敗しました。"
            "Secretsのprivate_key等を確認してください。"
        ) from e


# 認証とスプレッドシートは、rerun のたびに作り直さず使い回す。
@st.cache_resource(show_spinner=False)
def get_google_spreadsheet():
    """Google Sheetsを開く。"""

    sheet_id = get_secret_or_env("GOOGLE_SHEET_ID")

    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_IDが設定されていません。")

    try:
        credentials = get_google_credentials()
        client = gspread.authorize(credentials)
        return client.open_by_key(sheet_id)
    except Exception as e:
        raise ConnectionError(
            "Googleスプレッドシートを開けませんでした。\n\n"
            "以下を確認してください。\n"
            "・GOOGLE_SHEET_IDが正しい\n"
            "・サービスアカウントにスプレッドシートを共有している\n"
            "・サービスアカウントに編集権限がある"
        ) from e


def get_storage():
    return SheetStorage(get_google_spreadsheet())


# 保存一覧は入力のたびに読み直さないよう、60秒キャッシュする。
# 保存・削除のあとは clear() して最新の一覧を読み直す。
@st.cache_data(ttl=60, show_spinner=False)
def get_saved_data_options():
    """画面表示用の保存パターン一覧を取得する。"""

    return get_storage().list_saved()


def save_named_data_to_google_sheets(save_name, overwrite_save_id=None):
    """現在の画面を指定した名前で保存する。"""

    settings = {
        key: st.session_state.get(key, default) for key, default in SETTING_DEFAULTS.items()
    }

    try:
        save_id, save_name = get_storage().save(
            save_name, st.session_state.products, settings, overwrite_save_id=overwrite_save_id
        )
    finally:
        get_saved_data_options.clear()

    st.session_state.current_save_id = save_id
    st.session_state.current_save_name = save_name


def load_named_data_from_google_sheets(save_id):
    """指定save_idの保存データを読み込み、画面に反映する。"""

    record, products, settings = get_storage().load(save_id)

    st.session_state.products = products

    for key in SETTING_DEFAULTS:
        st.session_state[key] = settings[key]

    st.session_state.current_save_id = record["save_id"]
    st.session_state.current_save_name = record["name"]
    st.session_state.selected_saved_data_id = record["save_id"]

    st.session_state.widget_version = int(st.session_state.get("widget_version", 0)) + 1


def delete_named_data_from_google_sheets(save_id):
    """指定save_idの保存データを削除する。"""

    try:
        remaining = get_storage().delete(save_id)
    finally:
        get_saved_data_options.clear()

    if st.session_state.get("current_save_id") == save_id:
        st.session_state.current_save_id = ""
        st.session_state.current_save_name = ""

    if st.session_state.get("selected_saved_data_id") == save_id:
        st.session_state.selected_saved_data_id = remaining[0]["save_id"] if remaining else ""
