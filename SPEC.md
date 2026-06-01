# プロジェクト仕様書: Recipe Cliper

## 1. プロジェクト概要

### 1.1. 目的
YouTubeで見つけた料理動画のレシピ情報（材料、手順など）を、簡単な操作でNotionの指定データベースに自動的に登録・整理するためのツールを提供する。

### 1.2. 主要機能
1.  **URL入力UI:** ユーザーがYouTubeの料理動画URLを入力できるWebインターフェース。
2.  **YouTube動画字幕取得:** 入力されたURLの動画から`youtube-transcript-api`を使用して字幕テキストを取得する。字幕が存在しない動画はエラーとして扱う。
3.  **レシピ情報抽出:** 字幕テキストと動画メタデータから、AIモデル（Gemini API）を利用してレシピに関連する情報（材料リスト、調理手順など）を構造化データとして抽出する。
4.  **Notion DB連携:** 抽出されたレシピ情報を、ユーザーが指定したNotionデータベースに新しいページとして追加する。
5.  **Agent-to-Agent (A2A) アーキテクチャ:** 各主要機能（字幕取得、レシピ抽出、Notion連携）を独立したAIエージェントとして実装し、A2Aプロトコルを通じて連携させる。

### 1.3. ターゲットユーザー
*   料理が好きで、オンライン動画からレシピを収集するユーザー。
*   収集したレシピをNotionで効率的に管理したいユーザー。
*   手動での転記作業を自動化したいユーザー。

### 1.4. 技術スタック
*   **バックエンド:** Python 3.12
*   **Webフレームワーク:** Flask
*   **WSGIサーバー:** Waitress（本番環境用）
*   **コンテナ化:** Docker, Docker Compose V2
*   **依存関係管理:** Poetry（すべてのコンポーネントで統一）
*   **字幕取得:** youtube-transcript-api 1.x
*   **動画メタデータ取得:** yt-dlp
*   **レシピ抽出:** Gemini API（`gemini-flash-latest` - 常に最新のFlashモデルを使用）
*   **Notion連携:** Notion API, `notion-client` (Pythonライブラリ)
*   **エージェント間通信:** Agent-to-Agent (A2A) Protocol
*   **環境変数管理:** python-dotenv
*   **ロギング:** 標準ライブラリ logging
*   **フロントエンド:** HTML, CSS, JavaScript + Flaskテンプレート

---

## 2. UX/UIデザイン

### 2.1. 画面構成
シンプルで単一ページのWebアプリケーション。

*   **ヘッダー:** アプリケーションタイトル
*   **入力セクション:**
    *   ラベル: "YouTube動画のURLを入力してください"
    *   入力フィールド: テキスト入力 (URLペースト用)
    *   実行ボタン: 「レシピをNotionに登録」
*   **ステータス表示セクション:**
    *   処理中はハンバーガーキャラクターのアニメーションと「処理中です。しばらくお待ちください。」を表示。
    *   完了またはエラー時にアニメーションが消え、結果を表示。
*   **結果表示セクション:**
    *   成功時: 完了メッセージと作成されたNotionページへのリンクを表示。
    *   失敗時: エラーの内容を表示。
*   **アニメーション・キャラクター:**
    *   処理中にハンバーガーキャラクターがスケートボードで左から右へ移動するアニメーションを表示。
    *   スケートアニメーションは「左→右のみ」の一方向ループ。

### 2.2. ユーザーストーリー
1.  ユーザーはブラウザでアプリケーションにアクセスする。
2.  ユーザーはYouTube料理動画のURLを入力フィールドにペーストする。
3.  ユーザーは「レシピをNotionに登録」ボタンをクリックする。
4.  システムはバックグラウンドで処理を開始し、ハンバーガーアニメーションを表示する。
5.  システムは字幕取得 → レシピ抽出 → Notion登録の順に処理を行う。
6.  全ての処理が正常に完了すると、完了メッセージとNotionページへのリンクが表示される。
7.  途中でエラーが発生した場合、エラーの内容が表示される。

### 2.3. デザイン原則
*   **シンプル:** ユーザーが必要な操作はURLの入力とボタンクリックのみ。
*   **明確なフィードバック:** 処理中・成功・失敗をユーザーに明確に伝える。
*   **効率性:** 手動でのコピー＆ペーストや情報整理の手間を大幅に削減する。

---

## 3. 機能仕様

### 3.1. YouTube動画処理エージェント
*   **目的:** YouTube URLを受け取り、字幕テキストと動画メタデータを取得して次のエージェントに転送する。
*   **入力 (A2A Task):** `message.parts` に `youtube_url` を含む `DataPart` または `TextPart`。
*   **処理フロー:**
    1.  URL抽出・検証。
    2.  `yt-dlp`を使用してビデオメタデータ（動画タイトル、チャンネル名、サムネイルURL）を取得。
    3.  字幕取得:
        a. `youtube-transcript-api`を使用して手動追加された字幕を優先的に取得。手動字幕がない場合は自動生成字幕を取得。
        b. 優先言語順（デフォルト: `["ja", "en"]`）で検索。
        c. 字幕が取得できない場合はエラーを返す（音声文字起こしへのフォールバックなし）。
    4.  タスク状態をメモリ（`task_states`）に保存。
    5.  字幕テキストとメタデータをレシピ抽出エージェントに転送。転送結果（成功/失敗）を`task_states`に反映。
*   **出力 (A2A Task):**
    *   成功時: `status: "completed"`, `artifacts`: 字幕テキスト (`text/plain`)、ビデオメタデータ (`application/json`)
    *   失敗時: `status: "failed"`, `error`: エラーコードとメッセージ
*   **設定オプション:**
    *   `USE_SUBTITLES`: YouTube字幕取得機能の有効/無効（デフォルト: `True`）
    *   `SUBTITLE_LANG`: 取得する字幕の優先言語リスト（デフォルト: `["ja", "en"]`）
*   **エンドポイント:** `/.well-known/agent.json`, `/tasks/send`, `/tasks/get`, `/health`
*   **主要関数:**
    *   `download_subtitles()`: YouTube動画から字幕を取得（youtube-transcript-api使用）
    *   `send_to_next_agent()`: 次のエージェントにタスクデータを送信し、実際のレスポンス結果を返す
    *   `discover_agents()`: スキル・能力・コンテンツタイプに基づいて他のエージェントを発見
*   **現状:** 字幕取得に`youtube-transcript-api 1.x`を使用。動画タイトルを含むメタデータの取得・連携を実装。タスク状態をメモリ管理し`/tasks/get`が実際のステータスを返すよう実装。下流エージェントの失敗を正しく上流に伝播するよう修正。ヘルスチェックを実装。

### 3.2. レシピ抽出エージェント
*   **目的:** 字幕テキストと動画メタデータから、レシピ情報（料理名、カテゴリ、難易度、材料、手順）を抽出・整形しJSONデータとして提供する。
*   **入力 (A2A Task):** `metadata` に `youtube_url`, `channel_name`, `thumbnail_url`, `video_title`。`message.parts` に字幕テキスト (`text/plain`)。
*   **処理フロー:**
    1.  入力から字幕テキスト・YouTube URL・チャンネル名・サムネイルURL・動画タイトルを取得。
    2.  Gemini API (`gemini-flash-latest`, JSONモード) にプロンプトを送信してレシピ情報を抽出。
        *   動画タイトルを最優先で参照し料理名を特定（宣伝文句・記号等は除去）。
        *   429エラー（RPM制限）の場合は自動リトライ。日次上限（RPD）超過の場合は即座にエラーを返す。
    3.  LLM応答のJSONを検証し、不足フィールドを自動補完。
    4.  抽出したレシピデータをNotion連携エージェントに転送。転送結果に基づき`task_status`を更新。
*   **出力 (A2A Task):**
    *   成功時: `status: "completed"`, `metadata.notion_url`: 作成されたNotionページURL
    *   失敗時: `status: "failed"`, `error`: エラー情報（Gemini APIエラー・Notion登録エラーを含む）
*   **抽出フィールド:** `recipe_name`, `youtube_url`, `channel_name`, `thumbnail_url`, `category`, `difficulty`, `ingredients`, `instructions`
*   **エンドポイント:** `/.well-known/agent.json`, `/tasks/send`, `/health`
*   **主要関数:**
    *   `extract_recipe_from_text()`: 字幕テキストとメタデータからGemini APIでレシピ情報を抽出
    *   `send_to_next_agent()`: Notion連携エージェントにタスクを転送し実際のレスポンスを返す
*   **現状:** `gemini-flash-latest`を使用して常に最新のFlashモデルを自動選択。動画タイトルをプロンプトに含め料理名抽出精度を向上。RPM/RPDを区別したリトライ処理を実装。Notion登録失敗を適切にエラーとして伝播するよう修正。

### 3.3. Notion連携エージェント
*   **目的:** 抽出されたレシピ情報を指定Notion DBに追加する。
*   **入力 (A2A Task):** `message.parts` にレシピ情報JSON (`application/json`)。
*   **処理フロー:**
    1.  入力JSONからレシピデータを取得・検証。
    2.  Notion APIで入力データをDBプロパティにマッピング。
    3.  サムネイル画像（外部画像ブロック）とYouTubeリンクをページ本文に追加。
    4.  Notion API (`pages.create`) でページを作成。
    5.  作成したページのURLをレスポンスのメタデータに含めて返す。
*   **出力 (A2A Task):**
    *   成功時: `status: "completed"`, `metadata.notion_url`: 作成されたNotionページURL（HTTP 200）
    *   失敗時: `status: "failed"`, `error`: エラー情報（HTTP 200 ※A2Aプロトコル準拠）
*   **Notion DBプロパティ:**

    | プロパティ名 | タイプ |
    |---|---|
    | 料理名 | タイトル (Title) |
    | 動画チャンネル名 | テキスト (Text) |
    | カテゴリ | マルチセレクト (Multi-select) |
    | 難易度 | セレクト (Select) |
    | 材料リスト | テキスト (Text) |
    | 調理手順 | テキスト (Text) |
    | 料理動画URL | URL |

*   **エンドポイント:** `/.well-known/agent.json`, `/tasks/send`, `/health`
*   **現状:** A2Aプロトコルに準拠し失敗時もHTTP 200で`status: "failed"`を返すよう修正（HTTP 500から変更）。サムネイル画像をページ本文に表示する機能を実装。

### 3.4. フロントエンドUI / メインコントローラー
*   **目的:** ユーザーインターフェースを提供し、YouTube動画処理エージェントへのタスク送信・状態ポーリング・結果表示を担当する。
*   **処理フロー:**
    1.  YouTube URLを受け取りYouTubeエージェントに`/tasks/send`を送信。
    2.  3秒間隔でYouTubeエージェントの`/tasks/get`をポーリング。
    3.  `status: "completed"` → 成功UI（NotionページURL付き）を表示。
    4.  `status: "failed"` → エラーUI（エラーメッセージ付き）を表示。
*   **エンドポイント:** `/submit` (POST), `/status/<task_id>` (GET), `/health`
*   **現状:** エラー表示を適切に実装（タイムアウト・エラー回数による誤った完了判定を削除）。Notionリンクの重複表示バグを修正（実行のたびに蓄積される問題を解消）。

---

## 4. A2A連携アーキテクチャ

```
ユーザー (ブラウザ)
    ↓ YouTube URL
frontend (port 5003)
    ↓ /tasks/send
youtube-agent (port 5000)  ← 字幕取得・メタデータ取得
    ↓ 自律的に次エージェントへ転送
recipe-extractor (port 5001)  ← Gemini APIでレシピ抽出
    ↓ 自律的に次エージェントへ転送
notion-agent (port 5002)  ← Notion DBへ登録
    ↓ 結果（notion_url）を上流に返却
frontend ← ポーリングで最終結果を取得し表示
```

*   各エージェントはA2Aプロトコルに基づき `/tasks/send` でタスクを受け付け、同期的に処理して次エージェントへ転送する。
*   エラーが発生した場合、`status: "failed"` が上流エージェントへ伝播し、最終的にフロントエンドのエラー表示に反映される。
*   フロントエンドはYouTubeエージェントの`/tasks/get`のみをポーリングする。YouTube→レシピ→Notionの全連鎖が完了（または失敗）してから`task_states`が更新される。
*   各エージェントにはヘルスチェックエンドポイント (`/health`) を実装し、Docker Composeのヘルスチェック機能と連携してフロントエンドの起動タイミングを制御する。

---

## 5. プロジェクト構造

### 5.1. ディレクトリ構造

```
recipe-cliper/
│
├── agents/                           # 各エージェントのディレクトリ
│   ├── youtube_agent/               # YouTube字幕・メタデータ取得エージェント
│   │   ├── main.py                  # メインコード
│   │   ├── Dockerfile               # Dockerfile
│   │   ├── pyproject.toml           # 依存関係定義
│   │   └── agent_card.json          # エージェント定義
│   │
│   ├── recipe_agent/                # レシピ抽出エージェント
│   │   ├── main.py                  # メインコード
│   │   ├── recipe_extractor.py      # レシピ抽出ロジック（Gemini API）
│   │   ├── Dockerfile               # Dockerfile
│   │   ├── pyproject.toml           # 依存関係定義
│   │   ├── poetry.lock              # 依存関係ロックファイル
│   │   └── agent_card.json          # エージェント定義
│   │
│   └── notion_agent/                # Notion連携エージェント
│       ├── main.py                  # メインコード
│       ├── notion_handler.py        # Notion API連携ロジック
│       ├── Dockerfile               # Dockerfile
│       ├── pyproject.toml           # 依存関係定義
│       ├── poetry.lock              # 依存関係ロックファイル
│       └── agent_card.json          # エージェント定義
│
├── frontend/                        # フロントエンドUI
│   ├── main.py                      # メインコード（Flask）
│   ├── templates/
│   │   └── index.html               # メインページ
│   ├── static/
│   │   ├── css/style.css            # スタイルシート
│   │   └── js/main.js               # フロントエンドロジック
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── poetry.lock
│
├── tests/
│   └── integration_test.py          # 統合テスト
│
├── docker-compose.yml               # Docker Compose設定（ヘルスチェック含む）
├── .env                             # 環境変数（Gitignore対象）
├── .env.example                     # 環境変数のサンプル
├── .gitignore
├── SPEC.md                          # 本仕様書
└── README.md
```

### 5.2. Docker構成

各エージェントは独立したコンテナとして実行されます。`docker-compose.yml` でヘルスチェックを設定し、全エージェントの準備が完了してからフロントエンドが起動します。

| サービス名 | ポート | 役割 |
|---|---|---|
| youtube-agent | 5000 | YouTube字幕取得・メタデータ取得 |
| recipe-extractor | 5001 | Gemini APIによるレシピ抽出 |
| notion-agent | 5002 | Notion DBへの登録 |
| frontend | 5003 | ユーザーインターフェース |

### 5.3. 依存関係管理
*   すべてのエージェントで **Poetry** を使用して依存関係を管理。
*   `youtube_agent` は `poetry.lock` をリポジトリに含めず、ビルド時に `poetry lock` で再生成する。これは `youtube-transcript-api` のバージョンをpipで上書きインストールするため。
*   `recipe_agent`・`notion_agent`・`frontend` は `poetry.lock` をリポジトリに含め、全環境で一貫した依存関係バージョンを保証。

### 5.4. Docker最適化
*   `youtube_agent` の Dockerfileでは `poetry install` 後に `pip install "youtube-transcript-api>=1.0.0"` を実行し、poetryの依存解決制限を回避しつつ1.x系を確実に適用。
*   全エージェントにヘルスチェック (`curl -sf http://localhost:<port>/health`) を設定し、フロントエンドの`depends_on`に `condition: service_healthy` を指定。
*   `youtube_agent` は `start_period: 60s` を設定（起動処理のための余裕）。

---

## 6. インストールと実行方法

### 6.1. 必要条件
*   Docker および Docker Compose V2 (`docker compose` コマンドが使用できること)
*   Gemini API キー (Google AI Studio から取得)
*   Notion API キーと Database ID

### 6.2. Notionデータベースの準備
以下のプロパティを持つデータベースを作成し、インテグレーションを接続してください。

| プロパティ名 | タイプ | 備考 |
|---|---|---|
| 料理名 | タイトル | デフォルトの「名前」を変更 |
| 動画チャンネル名 | テキスト | |
| カテゴリ | マルチセレクト | |
| 難易度 | セレクト | 選択肢: 簡単・普通・難しい |
| 材料リスト | テキスト | |
| 調理手順 | テキスト | |
| 料理動画URL | URL | |

### 6.3. インストール手順

1.  リポジトリをクローン:
    ```bash
    git clone https://github.com/yusuke-nakakoji-japan/recipe-cliper.git
    cd recipe-cliper
    ```

2.  環境変数を設定:
    ```bash
    cp .env.example .env
    # .env を開いて各APIキーを設定
    ```

3.  ビルドと起動:
    ```bash
    docker compose up --build
    ```

### 6.4. 実行方法
```bash
docker compose up
```
ブラウザで `http://localhost:5003` にアクセス。

2回目以降はビルド済みイメージを使用するため起動が速くなります。

### 6.5. 停止
```bash
docker compose down
```

---

## 7. テスト

### 7.1. 統合テスト
`tests/integration_test.py` にYouTubeエージェントからNotionエージェントまでの一連のフローを検証するテストスイートを実装。

---

## 8. セキュリティ考慮事項

*   APIキーは環境変数として設定し、コードに直接記述しない（`.env` は `.gitignore` 対象）。
*   ユーザー入力（URL）はバックエンドで検証・サニタイズする。

---

## 9. 将来的な拡張

*   **認証機能の追加:** 特定ユーザーのみアクセスを許可する認証機能（Basic認証、OAuth等）を追加する。Oracle Cloud Free Tier + Cloudflare Accessによる構成が有力候補。
*   **マルチユーザー対応:** ユーザーごとに異なるNotion DBを指定できるようにする。
*   **レシピカテゴリのカスタマイズ:** ユーザーが自分でレシピカテゴリを定義・管理できるようにする。
*   **バッチ処理:** 複数のYouTube URLを一度に処理できるようにする。
*   **FastAPIへの移行:** async/awaitによる非同期処理・処理キャンセル機能を実装する。
*   **型アノテーションの活用:** Pydanticによる入出力の検証を導入する。
