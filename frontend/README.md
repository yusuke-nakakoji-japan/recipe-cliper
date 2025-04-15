# YouTubeレシピNotion自動登録ツール フロントエンド

## 概要

このフロントエンドは、YouTubeレシピNotion自動登録ツールのWebインターフェースを提供します。
ユーザーはYouTube動画のURLを入力するだけで、レシピ情報の自動抽出とNotionへの登録を行うことができます。

## 機能

- シンプルなURL入力フォーム
- 処理状況のリアルタイム表示
- レスポンシブデザイン
- 各処理ステップの進捗状況表示
- エラーハンドリングと通知

## 技術スタック

- **バックエンド**: Flask
- **フロントエンド**: HTML, CSS, JavaScript
- **通信**: Fetch API, ポーリング
- **スタイリング**: カスタムCSS
- **コンテナ化**: Docker

## 起動方法

### 単独起動（開発用）

```bash
cd frontend
pip install -r requirements.txt
python main.py
```

### Docker Compose（推奨）

プロジェクトのルートディレクトリで以下のコマンドを実行します：

```bash
docker-compose up -d
```

ブラウザで http://localhost:5003 にアクセスするとUIが表示されます。

## 環境変数

フロントエンドは以下の環境変数を使用します：

- `FLASK_APP`: Flaskアプリケーションファイル名（デフォルト: main.py）
- `FLASK_ENV`: 環境設定（development/production）
- `YOUTUBE_AGENT_URL`: YouTube処理エージェントのURL
- `RECIPE_AGENT_URL`: レシピ抽出エージェントのURL
- `NOTION_AGENT_URL`: Notion連携エージェントのURL
- `SECRET_KEY`: Flaskセッション用の秘密鍵

## 使用方法

1. アプリケーションにアクセスし、YouTubeの料理動画URLを入力フィールドに貼り付けます
2. 「レシピをNotionに登録」ボタンをクリックします
3. 処理状況が表示され、自動的に進捗が更新されます
4. 処理が完了すると、作成されたNotionページへのリンクが表示されます

## 注意事項

- このフロントエンドは、各エージェント（YouTube処理、レシピ抽出、Notion連携）と連携するために設計されています
- 正常に動作させるためには、すべてのエージェントが起動している必要があります 