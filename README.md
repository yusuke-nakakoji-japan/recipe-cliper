# Recipe Cliper

YouTubeの料理動画からレシピを抽出し、NotionのDBに格納するツール

## 概要

Recipe Cliperは、YouTube動画の字幕からレシピ情報を自動的に抽出し、Notionデータベースに整理して保存するツールです。AI技術を活用して動画コンテンツからレシピの材料や手順を抽出し、レシピコレクションを簡単に管理できます。

## 機能

- YouTube動画URLからの自動字幕抽出
- AI（Gemini API）によるレシピ情報の抽出
- 抽出したレシピのNotionデータベースへの自動登録
- シンプルなWebインターフェース

## システム構成

このプロジェクトは以下のコンポーネントで構成されています：

1. **YouTube Agent** - 動画からの字幕抽出 (Port 5000)
2. **Recipe Agent** - テキストからのレシピ情報抽出 (Port 5001)
3. **Notion Agent** - 抽出されたレシピのNotion登録 (Port 5002)
4. **Frontend** - ユーザーインターフェース (Port 5003)

## 必要条件

- Docker (20.10.x以上) および Docker Compose (2.x以上)
- Gemini API キー
- Notion API キーおよびデータベースID
- インターネット接続環境

## 事前準備

### 1. Gemini APIキーの取得

1. [Google AI Studio]にアクセスします
2. Googleアカウントでログインし、APIキーを作成します
3. 生成されたAPIキーをメモします（後で`.env`ファイルに設定します）

### 2. Notion APIの設定

1. [Notion Developers]にアクセスします
2. 「+ New integration」をクリックし、新しいインテグレーションを作成します
3. 名前（例: RecipeCliperIntegration）等の必要な設定を完了させます
4. 「Submit」をクリックし、生成された「Internal Integration Token」をメモします（後で`.env`ファイルに設定します）

### 3. Notionデータベースの作成

1. Notionにログインし、任意のページを開きます
2. `/database` と入力し、フルページデータベースを選択します
3. 以下のプロパティを持つデータベースを作成します：
   - `料理名` (タイプ: タイトル) - デフォルトで存在
   - `動画チャンネル名` (タイプ: テキスト)
   - `カテゴリ` (タイプ: マルチセレクト)
   - `難易度` (タイプ: セレクト) - オプション: 簡単、普通、難しい
   - `材料リスト` (タイプ: テキスト)
   - `調理手順` (タイプ: テキスト)
   - `料理動画URL` (タイプ: URL)
   - `作成日`(タイプ: 作成日時)
   - ※その他、任意で必要なプロパティーを追加してください（自動書き込みの対象外となります）
4. データベースの右上の「・・・」→「リンクをコピー」から、データベースのURLを取得します
5. データベースURLの末尾にある部分（`?v=...`の直前の英数字およびハイフン）をメモします。こちらがデータベースIDとなります（後で`.env`ファイルに設定します）

## セットアップ手順

### 1. リポジトリのクローン

```bash
git clone https://github.com/yusuke-nakakoji-japan/recipe-cliper.git
cd recipe-cliper
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env`ファイルを以下のように編集します：

```
GEMINI_API_KEY="ここにGemini APIキーを貼り付け"
NOTION_API_KEY="ここにNotion Integration Tokenを貼り付け"
NOTION_DATABASE_ID="ここにNotionデータベースIDを貼り付け"
```

### 3. Dockerイメージのビルドと起動

```bash
docker-compose up -d
```

初回起動時にはDockerイメージのビルドが行われるため、時間がかかることがあります。

### 4. アプリケーションへのアクセス

ブラウザで以下のURLにアクセスします：
```
http://localhost:5003
```

## 使用方法

1. ブラウザでアプリケーション（http://localhost:5003）にアクセスします
2. YouTubeの料理動画URLを入力フィールドに貼り付けます
3. 「クリップする」ボタンをクリックします
4. 処理状況が表示され、自動的に進捗が更新されます
5. 処理が完了すると、作成されたNotionページへのリンクが表示されます

## アプリケーションの停止と再起動

アプリケーションを停止するには：
```bash
docker-compose down
```

アプリケーションを再起動するには：
```bash
docker-compose up -d
```

## トラブルシューティング

### よくある問題と解決策

1. **APIキーエラー**
   - `.env`ファイルが正しく設定されているか確認してください
   - 各APIキーが有効であることを確認してください

2. **Notionデータベース接続エラー**
   - Notionデータベースに連携が正しく追加されているか確認してください
   - データベースIDが正しいことを確認してください

3. **Dockerビルドエラー**
   - Dockerとdocker-composeが最新バージョンであることを確認してください
   - `docker-compose down --volumes`を実行してから再度`docker-compose up -d`を試してください

4. **YouTubeエージェントのエラー**
   - YouTubeの動画が公開状態で、字幕が利用可能であることを確認してください
   - サポートされている言語（日本語、英語）の字幕があることを確認してください

### ログの確認方法

各コンポーネントのログを確認するには：

```bash
# すべてのログを表示
docker-compose logs -f

# 特定のサービスのログを表示
docker-compose logs -f youtube-agent
docker-compose logs -f recipe-extractor 
docker-compose logs -f notion-agent
docker-compose logs -f frontend
```

## ライセンス

このプロジェクトは商用利用制限付きライセンスのもとで提供されています。個人利用および教育・研究目的での利用は無償で許可されていますが、営利目的での使用は禁止されています。
商用利用をご希望の場合は、開発者にお問い合わせください。詳細については[LICENSE](LICENSE)ファイルを参照してください。