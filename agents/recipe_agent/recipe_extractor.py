# ファイル名: agents/recipe_agent/recipe_extractor.py
# 説明: Gemini APIを使用して文字起こしテキストからレシピ情報を抽出する機能

import os
import re
import time
import json
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from dotenv import load_dotenv
import logging

# === ロギング設定 ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# APIキーを環境変数から読み込む
# (このファイルが直接実行される場合や、呼び出し元で読み込まれていない場合を考慮)
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
else:
    logger.warning("警告: 環境変数 GEMINI_API_KEY が設定されていません。API呼び出しは失敗します。")


# === プロンプトテンプレート ===
# JSON部分の {} をエスケープ
RECIPE_EXTRACTION_PROMPT = """
あなたは料理レシピの抽出アシスタントです。
与えられた #YouTubeURL #動画タイトル #チャンネル名 #サムネイルURL 及びその動画の #文字起こしテキスト から、以下の情報を抽出し、指定されたJSON形式で出力してください。

1. 料理名（レシピタイトル）: #動画タイトル を参考に、料理そのものの名前のみを簡潔に抽出してください（例: 動画タイトルが「激安豚こま肉で作る老舗の味【炒り豚】」なら「炒り豚」）。価格・食材の説明・宣伝文句・記号は含めないでください。明確でない場合は「不明なレシピ」と記載
2. 料理のカテゴリ (例: 和食, イタリアン, 中華, デザート, etc.)
3. 料理の難易度 (簡単, 普通, 難しい のうちどれか): 動画の内容から推定して記載
4. 材料リスト: 各材料を「・材料名: 分量」の形式の文字列として配列に格納
5. 調理手順: 各手順を「1. 手順の説明文」のように数字と「.」で番号付きで配列に格納

出力は以下のJSON形式で厳密に従ってください。

```json
{{
  "recipe_name": "抽出した料理名",
  "youtube_url": "{{youtube_url}}",
  "channel_name": "{{channel_name}}",
  "thumbnail_url": "{{thumbnail_url}}",
  "category": ["抽出したカテゴリ"],
  "difficulty": "抽出した難易度",
  "ingredients": [
    "・材料名1: 分量1",
    "・材料名2: 分量2",
    ...
  ],
  "instructions": [
    "1. 手順の説明文",
    "2. 手順の説明文",
    ...
  ]
}}
```

#制約条件:
- カテゴリは必ず配列形式で出力してください（例: ["和食"] や ["イタリアン", "パスタ"] など）。
- 材料リストは必ず文字列の配列形式にしてください。辞書や他の形式は使用しないでください。
- 各材料は「材料名: 分量」の形式の文字列にしてください。
- 調理手順は誰が見てもレシピを再現できるように動画内の情報から可能な限り具体的に記載してください。
  - 調理時間（例: 「中火で3分炒める」）を含めてください
  - 使用する調理器具・材料・分量を明記してください
  - 調理の詳細（切り方、炒め方、火加減など）を明記してください
  - 複数の手順がある場合は、順番通りに分けて記載してください
  - 火加減（弱火、中火、強火など）を可能な限り記載してください
  - 調理テクニック（さっと炒める、弱火でじっくり煮るなど）を明記してください
- 不要な前置きやコメントは含めないでください。
- 勝手に情報を補完したり、動画内で紹介されていない情報を記載したりしないでください。
- formatは厳密に守ってください。

#YouTubeURL
{youtube_url}

#動画タイトル
{video_title}

#チャンネル名
{channel_name}

#サムネイルURL
{thumbnail_url}

#文字起こしテキスト
{transcript_text}
"""

def extract_recipe_from_text(transcript_text: str, youtube_url: str, channel_name: str = None, thumbnail_url: str = None, video_title: str = None) -> str | None:
    """
    文字起こしテキストとYouTube URLからGemini APIを使用してレシピ情報(JSON)を抽出する
    JSONモードを利用して出力の信頼性を高める
    
    Args:
        transcript_text (str): 文字起こしされたテキスト
        youtube_url (str): 対象のYouTube動画URL
        channel_name (str): YouTube動画のチャンネル名
        thumbnail_url (str): YouTube動画のサムネイルURL
    
    Returns:
        str | None: 抽出されたレシピ情報のJSON文字列。エラー時はNone
    """
    if not api_key:
        msg = "サーバー側でGemini APIキーが設定されていません。管理者にお問い合わせください。"
        logger.error(msg)
        raise RuntimeError(msg)

    try:
        model = genai.GenerativeModel('gemini-flash-latest')

        # プロンプトに文字起こしテキストとURLを埋め込む
        prompt = RECIPE_EXTRACTION_PROMPT.format(
            transcript_text=transcript_text,
            youtube_url=youtube_url,
            video_title=video_title or "",
            channel_name=channel_name or "不明",
            thumbnail_url=thumbnail_url or ""
        )

        # JSONモードを設定するための GenerationConfig
        generation_config = GenerationConfig(
            response_mime_type="application/json"
        )

        logger.info("Geminiにレシピ抽出リクエストを送信します...")
        MAX_RETRIES = 3
        response = None
        for attempt in range(MAX_RETRIES):
            try:
                response = model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    request_options={"timeout": 120}
                )
                break
            except Exception as api_err:
                err_str = str(api_err)
                if "429" in err_str:
                    # 1日の上限超過（RPD）はリトライしても解消しないため即座に失敗
                    if "PerDay" in err_str or "per_day" in err_str.lower():
                        msg = "1日のGemini API無料枠の上限に達しました。翌日以降に再試行してください。"
                        logger.error(msg)
                        raise RuntimeError(msg)
                    # 1分あたりの上限（RPM）は待機後にリトライ
                    if attempt < MAX_RETRIES - 1:
                        match = re.search(r'retry.*?(\d+)\s*s', err_str, re.IGNORECASE)
                        wait_sec = int(match.group(1)) + 5 if match else 60
                        logger.warning(f"RPM制限に達しました。{wait_sec}秒後にリトライします（{attempt+1}/{MAX_RETRIES}）")
                        time.sleep(wait_sec)
                    else:
                        msg = "Gemini APIのリクエスト制限（1分あたりの上限）に繰り返し達しました。しばらく時間をおいてから再試行してください。"
                        logger.error(msg)
                        raise RuntimeError(msg)
                else:
                    raise

        # JSONモードの場合、応答テキストが直接JSON文字列になることを期待
        if response and hasattr(response, 'text'):
            json_string = response.text
            try:
                # JSONとしてパースできるか検証
                parsed_json = json.loads(json_string)
                
                # 必要なメタデータが含まれていなければ追加
                modified = False
                
                if not parsed_json.get("youtube_url"):
                    parsed_json["youtube_url"] = youtube_url
                    modified = True
                    
                if not parsed_json.get("channel_name") and channel_name:
                    parsed_json["channel_name"] = channel_name
                    modified = True
                    
                if not parsed_json.get("thumbnail_url") and thumbnail_url:
                    parsed_json["thumbnail_url"] = thumbnail_url
                    modified = True
                
                # 変更があった場合はJSON文字列を更新
                if modified:
                    json_string = json.dumps(parsed_json, ensure_ascii=False)
                
                logger.info("レシピ抽出成功")
                return json_string
            except json.JSONDecodeError as json_err:
                msg = "AIが返したレシピデータを解析できませんでした。お手数ですが、もう一度お試しください。"
                logger.error(f"{msg}（詳細: {json_err}）")
                raise RuntimeError(msg)
        else:
            msg = "AIからレシピ情報を取得できませんでした。動画に十分な情報が含まれていない可能性があります。"
            logger.error(msg)
            raise RuntimeError(msg)

    except RuntimeError:
        raise  # ユーザー向けメッセージをそのまま上流へ伝播
    except Exception as e:
        logger.error(f"Gemini API呼び出し中または応答処理中に予期せぬエラーが発生しました: {e}")
        return None

if __name__ == '__main__':
    # テスト用途の場合のみ実行されるコード
    logger.info("このモジュールは直接実行されました。レシピ抽出機能をテストする場合に使用できます。") 