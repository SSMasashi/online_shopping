# online-shopping（Amazon・楽天 最安値振り分けアプリ）

## プロジェクト概要
- Amazon と楽天の価格を比べ、商品ごとに最安の購入先を振り分ける Streamlit アプリ
- Claude Code のマルチエージェント機能を学習するため、このアプリのリファクタリングを題材にしている

## 技術スタック
- Python 3.10 以上
- パッケージ管理: uv（pip は使用しない）
- フレームワーク: Streamlit（Streamlit Cloud にデプロイ）
- データ: Google Sheets（gspread + google-auth のサービスアカウント認証）
- テスト: pytest

## 開発ルール
- コメントとドキュメントは日本語で記述する
- パッケージの追加は `uv add` を使う
- テスト実行は `uv run pytest -v` を使う
- pip install は絶対に使わないこと
- アプリ起動コマンド: `uv run streamlit run src/buy_sl.py`

## Streamlit / デプロイ時の注意
- エントリポイントは `src/buy_sl.py`。Streamlit Cloud はこのファイルを直接実行する
- 認証情報や設定値は `st.secrets` から読む。ローカルでは `.streamlit/secrets.toml`（git 管理外）、本番では Streamlit Cloud の Secrets に設定する
- 秘密情報の実際の値をコード・ドキュメント・テストに書かないこと
- テストでは Google Sheets や外部 API に実際にアクセスしないこと（計算ロジックを切り出してテストするか、モックを使う）

## ディレクトリ構成
- src/ : アプリのソースコード。buy_sl.py は入口だけで、処理は src/shopping/ に分かれている（ui / calc / rakuten / storage / gsheets_app）
- src/shopping/ のモジュールは、import しただけで st.* を実行しないこと（st.set_page_config は buy_sl.py で最初に呼ぶ）
- tests/ : テストコード
- .claude/ : サブエージェント定義（code-reviewer、test-engineer、doc-writer）とスラッシュコマンド（/review、/test）
