# Amazon × 楽天 最安振り分け計算

Amazonと楽天市場、それぞれで同じ商品を買えるときに「ポイント還元まで含めた実質負担額」で比べると、どちらで買うのが本当にお得かは意外とわかりにくいものです。
このアプリは、商品ごとにAmazon・楽天の価格とポイント還元率を入力すると、楽天の「お買い物マラソン（買いまわり）」特典まで考慮したうえで、商品ごとに最も実質負担額が安くなる購入先の組み合わせを自動で計算してくれるStreamlitアプリです。

入口は `src/buy_sl.py` で、処理は `src/shopping/` に分かれています。Streamlit Cloud上で動かすことを想定しています。

## 主な機能

- **商品ごとのAmazon・楽天の価格入力**（1商品1カード。スマホでも縦に並んで見やすい）
  - 商品名と個数（1〜99）。価格・ポイント・買いまわりの判定はすべて個数分で計算
  - Amazon：価格・還元率（%）・「らくベビ割（10%OFF）」・商品URL（メモ）
  - 楽天：価格・還元率（%、通常の1%を除く）・商品URL。URLを貼り付けると、楽天市場商品検索APIから価格と還元率を自動取得
  - 価格が0の店は「扱いなし」として計算（両方0の商品は計算から除外）
- **最安の購入先の自動振り分け**
  - Amazon/楽天の組み合わせを総当たりで評価し、実質負担額が最も安くなる組み合わせを算出
  - 「すべて楽天より◯円お得」のようにお得額を表示し、「最適な振り分け」「すべてAmazon」「すべて楽天」を比較
  - 店ごとの**買い物リスト**を表示。URLがある商品には商品ページを開くボタン付き
  - 商品ごとの内訳と、Amazon/楽天ごとの詳細な計算内訳も確認できる
- **楽天お買い物マラソン（買いまわり）の考慮**（サイドバーで設定）
  - 買いまわり対象の最大ショップ数、対象となる最低金額（税込）、特典ポイントの上限、SPU倍率
- **入力内容のGoogle Sheetsへの保存・読み込み・削除**（サイドバー）
  - 「上書き保存」（読み込み中のデータを更新）と「別名で保存」（新しい名前で保存。同じ名前があれば保存しない）
  - 削除時は確認を表示
- 商品は最大15件まで登録可能

## 動作環境

- Python 3.10 以上
- [uv](https://docs.astral.sh/uv/)（パッケージ管理。pipは使用しません）
- 楽天ウェブサービスのアプリID・アフィリエイト設定（楽天商品URLからの自動取得機能を使う場合）
- Googleサービスアカウント（保存・読み込み機能を使う場合）

依存パッケージは `pyproject.toml` で管理されています（streamlit、gspread、google-auth）。

## ローカルでの起動方法

### 1. 依存関係のインストール

```bash
uv sync
```

### 2. Secretsの設定

後述の「[Secretsの設定](#secretsの設定)」を参考に `.streamlit/secrets.toml` を作成してください（このファイルは `.gitignore`済みで、リポジトリには含まれません）。

### 3. アプリの起動

```bash
uv run streamlit run src/buy_sl.py
```

起動後、ブラウザで `http://localhost:8501` が開きます。

## Secretsの設定

このアプリは認証情報や設定値を画面には表示せず、`st.secrets` から読み込みます。

- **ローカル環境**: プロジェクト直下に `.streamlit/secrets.toml` を作成する
- **Streamlit Cloud**: アプリ設定（Settings）の「Secrets」欄に、同じ内容をTOML形式で貼り付ける

### 必要なキー一覧

| キー名 | 用途 | 必須 |
| --- | --- | --- |
| `RAKUTEN_APP_ID` | 楽天ウェブサービスのアプリケーションID | 楽天URLからの自動取得機能を使う場合は必須 |
| `RAKUTEN_ACCESS_KEY` | 楽天ウェブサービスのアクセスキー | 同上 |
| `RAKUTEN_REFERER` | 楽天APIに登録したリファラURL | 同上 |
| `GOOGLE_SHEET_ID` | 保存先スプレッドシートのID | 保存・読み込み機能を使う場合は必須 |
| `gcp_service_account` | Googleサービスアカウントの認証情報（テーブル） | 同上 |

`gcp_service_account` には、少なくとも `type` / `project_id` / `private_key_id` / `private_key` / `client_email` / `client_id` / `token_uri` が必要です（コード内でこれらの存在を検証しています）。通常はGoogle Cloudで発行するサービスアカウントのJSONキーファイルの中身をそのままTOMLのテーブルとして貼り付ける形になります。

`RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_REFERER` は、Secretsに設定がない場合は同名の環境変数からも読み込まれます（ローカルでのフォールバック用途）。

### secrets.toml の記入例

```toml
# 楽天ウェブサービス
RAKUTEN_APP_ID = "your-rakuten-app-id"
RAKUTEN_ACCESS_KEY = "your-rakuten-access-key"
RAKUTEN_REFERER = "https://your-registered-referer.example.com/"

# Google Sheets（保存・読み込み機能）
GOOGLE_SHEET_ID = "your-google-spreadsheet-id"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\nyour-private-key-content\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project-id.iam.gserviceaccount.com"
client_id = "your-client-id"
token_uri = "https://oauth2.googleapis.com/token"
```

上記の値はすべてプレースホルダです。実際の秘密情報に置き換えて使用してください。

## Google Sheetsの準備

保存・読み込み機能を使うには、事前に以下の準備が必要です。

1. Google Cloudでプロジェクトを作成し、Google Sheets APIを有効化する（アプリが要求するスコープは `spreadsheets` のみ）
2. サービスアカウントを作成し、JSON形式の認証キーを発行する
3. 保存先にしたいGoogleスプレッドシートを用意し、そのスプレッドシートをサービスアカウントのメールアドレス（`client_email`）に対して編集権限で共有する
4. スプレッドシートのIDを控え、`GOOGLE_SHEET_ID` に設定する
5. 発行したサービスアカウントのJSONキーの内容を、上記の記入例のように `gcp_service_account` として設定する

アプリ側は、保存に必要な `saved_data` / `products` / `settings` の3つのワークシートが存在しない場合は自動的に作成するため、事前にシートやヘッダー行を手作業で用意する必要はありません。

## Streamlit Cloudへのデプロイ

1. このリポジトリをGitHubにpushする
2. [Streamlit Community Cloud](https://streamlit.io/cloud) にログインし、「New app」から対象のリポジトリ・ブランチを選択する
3. Main file path に `src/buy_sl.py` を指定する
4. アプリの Settings → Secrets に、上記の「secrets.toml の記入例」と同じ内容（実際の値に置き換えたもの）を貼り付けて保存する
5. デプロイを実行する

## ディレクトリ構成

```
online-shopping/
├── src/
│   ├── buy_sl.py            # アプリの入口（Streamlit Cloud が実行するファイル）
│   └── shopping/
│       ├── ui.py            # 画面の組み立て（main() と各部分の表示）
│       ├── calc.py          # 最安の振り分け計算（Streamlit に依存しない）
│       ├── rakuten.py       # 楽天APIからの価格・ポイント取得
│       ├── storage.py       # Google Sheets への保存・読み込み・削除
│       └── gsheets_app.py   # Secrets の読み込みと、保存処理のキャッシュ・画面状態の更新
├── tests/                   # pytest のテスト（uv run pytest -v で実行）
├── .claude/
│   ├── agents/              # Claude Codeのサブエージェント定義
│   │   ├── code-reviewer.md # コードレビュー専門エージェント（修正は行わず指摘のみ）
│   │   ├── test-engineer.md # テストコードの作成・実行を担当するエージェント
│   │   └── doc-writer.md    # ドキュメント（README・docstring等）作成を担当するエージェント
│   ├── commands/             # Claude Codeのカスタムスラッシュコマンド
│   │   ├── test.md          # 指定対象のテストを作成・実行するコマンド
│   │   └── review.md        # 指定対象をコードレビューするコマンド
│   └── settings.json         # Claude Codeの設定ファイル
├── pyproject.toml            # プロジェクト設定・依存関係定義
├── uv.lock                   # 依存関係のロックファイル
└── README.md                  # このファイル
```

## 開発

新しい依存パッケージを追加する場合は `uv add` を使用してください。

```bash
uv add <パッケージ名>
```

`pip install` は使用しません。
