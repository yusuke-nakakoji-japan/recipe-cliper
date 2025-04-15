# ファイル名: agents/notion_agent/notion_handler.py
# 説明: Notion APIを使用してレシピデータをNotionデータベースに登録する機能

import os
import logging
import json
from notion_client import Client, APIResponseError
from dotenv import load_dotenv

# === ロギング設定 ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# .envファイルから環境変数を読み込み
# notion_agentの親ディレクトリに.envがあると仮定
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    # 親ディレクトリに見つからない場合は現在のディレクトリから読み込み
    load_dotenv()

# === Notionクライアントの初期化 ===
NOTION_TOKEN = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN:
    logger.error("環境変数 NOTION_API_KEY が見つかりません。")
    # トークンが必須の場合はエラーを発生させるかexitを検討
if not DATABASE_ID:
    logger.error("環境変数 NOTION_DATABASE_ID が見つかりません。")
    # DB IDが必須の場合はエラーを発生させるかexitを検討

notion = None
if NOTION_TOKEN:
    try:
        notion = Client(auth=NOTION_TOKEN)
        logger.info("Notionクライアントの初期化に成功しました。")
    except Exception as e:
        logger.error(f"Notionクライアントの初期化に失敗しました: {e}")

def map_recipe_to_notion_properties(recipe_data: dict) -> dict:
    """
    抽出されたレシピデータ辞書をNotionデータベースのプロパティ形式にマッピングする
    
    Args:
        recipe_data (dict): レシピ情報を含む辞書データ
        
    Returns:
        dict: Notionデータベースプロパティ形式に変換されたデータ
    """
    properties = {}

    # --- 指定された日本語プロパティ名に基づいてマッピング ---

    # 料理名 (Titleプロパティ) - recipe_dataに'recipe_name'が存在すると想定
    if 'recipe_name' in recipe_data and recipe_data['recipe_name']:
         # 'title'プロパティは特別で、リッチテキストオブジェクトのリストが必要
        properties["料理名"] = {
            "title": [{"text": {"content": str(recipe_data['recipe_name'])}}]
        }
    else:
        # 名前がない場合はデフォルトのタイトルを追加
        properties["料理名"] = {
            "title": [{"text": {"content": "名称未設定のレシピ"}}]
        }

    # 動画チャンネル名 (Textプロパティ) - recipe_dataに'channel_name'が存在する場合に処理
    if 'channel_name' in recipe_data and recipe_data['channel_name']:
        properties["動画チャンネル名"] = {
            "rich_text": [{"text": {"content": str(recipe_data['channel_name'])}}]
        }
    # カテゴリ (SelectまたはMulti-selectプロパティ) - recipe_dataに'category'が存在すると想定
    # 実際のNotion DBのプロパティタイプに基づいて調整（マルチセレクト優先）
    if 'category' in recipe_data and recipe_data['category']:
        category_value = recipe_data['category']
        if isinstance(category_value, list):  # マルチセレクト入力を処理
            # マルチセレクト用のオプションがNotion DBに存在することを確認
             properties["カテゴリ"] = {"multi_select": [{"name": str(cat)} for cat in category_value if cat]}  # 空文字列を除外
        elif isinstance(category_value, str) and category_value:  # セレクト入力を処理
            # 文字列の場合でもmulti_select形式に変換（Notionデータベースの要件に合わせる）
            properties["カテゴリ"] = {"multi_select": [{"name": category_value}]}
        else:
            logger.warning(f"無効または空のカテゴリ値: {category_value}")

    # 難易度 (Selectプロパティ) - recipe_dataに'difficulty'が存在する場合に処理
    if 'difficulty' in recipe_data and recipe_data['difficulty']:
        difficulty_value = str(recipe_data['difficulty'])
        properties["難易度"] = {"select": {"name": difficulty_value}}
    else:
        # 難易度が指定されていない場合はデフォルトの「普通」を設定
        properties["難易度"] = {"select": {"name": "普通"}}

    # 材料リスト (Textプロパティ)
    if 'ingredients' in recipe_data and recipe_data['ingredients']:
        ingredients = recipe_data['ingredients']
        content = ""
        
        if isinstance(ingredients, list):
            # リスト内の空文字列を除外して結合
            valid_ingredients = [str(item) for item in ingredients if item]
            content = "\n".join(valid_ingredients)
        elif isinstance(ingredients, dict):
            # 辞書型の場合は「材料名: 分量」形式に変換
            valid_items = [f"{key}: {value}" for key, value in ingredients.items() if key and value]
            content = "\n".join(valid_items)
        else:
            content = str(ingredients)
        
        if content:  # 処理後に内容がある場合のみ追加
            properties["材料リスト"] = {
                "rich_text": [{"text": {"content": content[:2000]}}]
            }

    # 調理手順 (Textプロパティ) - recipe_dataに'instructions'が存在すると想定
    if 'instructions' in recipe_data and recipe_data['instructions']:
        content = recipe_data['instructions']
        if isinstance(content, list):
            content = "\n".join([str(instruction) for instruction in content if instruction])
        else:
            content = str(content)
        if content:
            properties["調理手順"] = {
                "rich_text": [{"text": {"content": content[:2000]}}]
            }

    # 料理動画URL (URLプロパティ) - recipe_dataに'youtube_url'が存在すると想定
    if 'youtube_url' in recipe_data and recipe_data['youtube_url'] and isinstance(recipe_data['youtube_url'], str):
        properties["料理動画URL"] = {"url": recipe_data['youtube_url']}

    # 作成日 (Created Timeプロパティ) - これはNotionによって自動的に処理される

    logger.debug(f"マッピングされたプロパティ: {properties}")
    return properties

def add_recipe_to_notion(recipe_data: dict) -> str | None:
    """
    レシピデータを含む新しいページを指定されたNotionデータベースに追加する
    
    Args:
        recipe_data (dict): 抽出されたレシピ情報を含む辞書。
                キーは map_recipe_to_notion_properties で使用されるもの
                (例: 'recipe_name', 'category', 'ingredients' など) と一致することが望ましい。
    
    Returns:
        str | None: 新しく作成されたNotionページのURL。エラーが発生した場合はNone。
    """
    if not notion or not DATABASE_ID:
        logger.error("NotionクライアントまたはデータベースIDが設定されていません。")
        return None
    if not recipe_data:
        logger.error("空のレシピデータを受け取りました。")
        return None

    try:
        properties = map_recipe_to_notion_properties(recipe_data)

        # マッピング後にタイトルなどの必須プロパティが欠落していないか確認
        if "料理名" not in properties or not properties["料理名"]["title"]:
             logger.error("必須プロパティ '料理名' (タイトル) のマッピングに失敗しました。")
             # フォールバックとしてデフォルトのタイトルを使用
             properties["料理名"] = {"title": [{"text": {"content": "タイトル処理エラー"}}]}

        logger.info(f"Notionページ作成試行 (DB: {DATABASE_ID})")  # デバッグしやすいようにDB IDをログに出力

        # ページ本文を準備（サムネイル画像を含める）
        children = []
        
        # サムネイル画像を追加（エラーハンドリング強化）
        if 'thumbnail_url' in recipe_data and recipe_data['thumbnail_url']:
            try:
                children.append({
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {
                            "url": recipe_data['thumbnail_url']
                        }
                    }
                })
                logger.info("サムネイル画像ブロックを追加しました")
            except Exception as e:
                logger.warning(f"サムネイル画像ブロックの追加に失敗しました: {e}")
                # エラーが発生しても処理を続行（非クリティカル）
                try:
                    # 代わりにURLをリンクとして追加
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {
                                    "content": "サムネイル画像: ",
                                }
                            }, 
                            {
                                "type": "text",
                                "text": {
                                    "content": recipe_data['thumbnail_url'],
                                    "link": {"url": recipe_data['thumbnail_url']}
                                }
                            }]
                        }
                    })
                    logger.info("サムネイルURLをリンクとして追加しました")
                except Exception:
                    logger.warning("サムネイルURLのリンク追加にも失敗しました")
        
        # YouTubeリンクも追加
        if 'youtube_url' in recipe_data and recipe_data['youtube_url']:
            try:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {
                                "content": "YouTube動画: ",
                            }
                        }, 
                        {
                            "type": "text",
                            "text": {
                                "content": recipe_data['youtube_url'],
                                "link": {"url": recipe_data['youtube_url']}
                            }
                        }]
                    }
                })
                logger.info("YouTube動画リンクを追加しました")
            except Exception as e:
                logger.warning(f"YouTube動画リンクの追加に失敗しました: {e}")

        # ページ作成パラメータ
        create_params = {
            "parent": {"database_id": DATABASE_ID},
            "properties": properties
        }
        
        # ページ本文がある場合は追加
        if children:
            create_params["children"] = children

        response = notion.pages.create(**create_params)
        
        page_url = response.get("url")
        if page_url:
             logger.info(f"Notionページの作成に成功しました: {page_url}")
        else:
             # ページは作成されたがURLが応答に含まれない場合
             logger.warning("ページは作成されましたが、URLが取得できませんでした")
             page_url = f"https://notion.so/{DATABASE_ID}"
        
        return page_url
        
    except APIResponseError as e:
        # NotionのAPIエラー（詳細なエラー情報があるので別に処理）
        error_code = e.code if hasattr(e, 'code') else "unknown"
        error_message = e.body.get("message", str(e)) if hasattr(e, 'body') and isinstance(e.body, dict) else str(e)
        logger.error(f"Notion API エラー ({error_code}): {error_message}")
        
        # 特定のエラーに対する詳細情報
        if error_code == "validation_error":
            property_details = []
            if hasattr(e, 'body') and isinstance(e.body, dict):
                for detail in e.body.get("errors", []):
                    property_details.append(f"{detail.get('path', ['unknown'])[-1]}: {detail.get('message', '不明なエラー')}")
            
            if property_details:
                logger.error(f"プロパティエラー詳細: {', '.join(property_details)}")
        
        return None
    except Exception as e:
        logger.exception(f"Notionページ作成中に予期せぬエラーが発生しました: {e}")
        return None

# テスト用
if __name__ == "__main__":
    logger.info("このモジュールは直接実行されました。.envファイルの設定を確認します。")
    logger.info(f"NOTION_TOKEN読み込み済み: {'はい' if NOTION_TOKEN else 'いいえ'}")
    logger.info(f"NOTION_DATABASE_ID読み込み済み: {'はい' if DATABASE_ID else 'いいえ'}")
