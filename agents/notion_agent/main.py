# ファイル名: agents/notion_agent/main.py
# 説明: レシピデータをNotionデータベースに登録するエージェント

#----------------------------------------------
# 1. インポート
#----------------------------------------------
# 標準ライブラリ
import os
import copy
import json
import uuid
import logging
from pathlib import Path

# サードパーティライブラリ
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from waitress import serve

# 自作モジュール
from notion_handler import add_recipe_to_notion, map_recipe_to_notion_properties

#----------------------------------------------
# 2. 定数と設定
#----------------------------------------------
# Agent Cardパス
AGENT_CARD_PATH = Path(__file__).parent / "agent_card.json"
# デフォルトポート (他のエージェントと衝突しないように設定)
DEFAULT_PORT = 5002  # ポート番号を recipe_agent (5001想定) と異なるものに設定

#----------------------------------------------
# 3. Flask初期化とロギング設定
#----------------------------------------------
# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flaskアプリケーション初期化
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
# notion_handler のログレベルも必要に応じて設定
# notion_logger.setLevel(logging.DEBUG)

#----------------------------------------------
# 4. API関連の関数（エンドポイント）
#----------------------------------------------
@app.route('/.well-known/agent.json', methods=['GET'])
def get_agent_card():
    """
    Agent Card情報を提供する (標準A2A仕様に従って)
    
    Returns:
        dict: エージェントカード情報を含むJSONレスポンス
    """
    # Docker Compose環境などを考慮し、リクエストヘッダーからHostを取得試行
    host_url = request.host_url.rstrip('/')
    # 環境変数で上書き可能にする（より堅牢）
    server_base_url = os.environ.get('A2A_SERVER_URL', host_url)
    if not server_base_url:
         server_base_url = f"http://localhost:{DEFAULT_PORT}"  # フォールバック
         logger.warning(f"サーバーURLをリクエストまたは環境変数から取得できませんでした。代替値を使用します: {server_base_url}")

    # agent_card.jsonファイルからエージェント情報を読み込む
    try:
        with open(AGENT_CARD_PATH, 'r', encoding='utf-8') as file:
            agent_info = json.load(file)
            # URLだけは動的に設定
            agent_info["url"] = server_base_url
    except FileNotFoundError as e:
        logger.error(f"エージェントカードファイルが見つかりません: {AGENT_CARD_PATH}: {e}")
        return jsonify({"error": f"エージェントカードファイルが見つかりません: {e}"}), 500
    except json.JSONDecodeError as e:
        logger.error(f"エージェントカードファイルのJSON形式が不正です: {AGENT_CARD_PATH}: {e}")
        return jsonify({"error": f"エージェントカードファイルのJSON形式が不正です: {e}"}), 500
    except Exception as e:
        logger.error(f"エージェントカードの読み込み中に予期せぬエラーが発生しました: {AGENT_CARD_PATH}: {e}")
        return jsonify({"error": f"エージェントカードの読み込みに失敗しました: {e}"}), 500

    return jsonify(agent_info)

@app.route('/query-skill', methods=['POST'])
def query_skill():
    """特定のスキルが利用可能かどうかを確認するエンドポイント"""
    if not request.is_json:
        logger.error("Request is not JSON")
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    skill_name = data.get('skill')
    capability = data.get('capability')
    
    if not skill_name and not capability:
        return jsonify({
            "error": {
                "code": "BadRequest",
                "message": "Missing 'skill' or 'capability' parameter in request."
            }
        }), 400
        
    # エージェントカードから利用可能なスキルを取得
    try:
        with open(AGENT_CARD_PATH, 'r', encoding='utf-8') as f:
            agent_card = json.load(f)
            available_skills = [skill.get('name') for skill in agent_card.get('skills', [])]
    except Exception as e:
        logger.error(f"Error reading agent card: {e}")
        available_skills = ["notion_registration", "recipe_database_management", "data_validation"]
    
    # スキル名が指定された場合の処理
    if skill_name:
        # 完全一致または部分一致でスキルを確認
        skill_available = any(s.lower() in skill_name.lower() or skill_name.lower() in s.lower() for s in available_skills)
        
        # 特定のスキルの詳細情報
        skill_details = {}
        if skill_name.lower() in "notion_registration" or "notion" in skill_name.lower() or "registration" in skill_name.lower():
            skill_details = {
                "requiredParameters": ["recipe_name", "ingredients", "instructions"],
                "optionalParameters": ["category", "difficulty", "youtube_url", "channel_name", "thumbnail_url"],
                "inputFormat": "JSON object with recipe information"
            }
            skill_available = True
        elif skill_name.lower() in "data_validation" or "validate" in skill_name.lower():
            skill_details = {
                "requiredParameters": ["data"],
                "returns": "Validated and preprocessed data"
            }
            skill_available = True
        elif skill_name.lower() in "recipe_database_management" or "database" in skill_name.lower():
            skill_details = {
                "requiredParameters": ["action", "data"],
                "supportedActions": ["create", "update", "delete", "query"]
            }
            skill_available = True
        
        return jsonify({
            "available": skill_available,
            "details": skill_details if skill_available else {}
        }), 200
    
    # 能力（capability）が指定された場合の処理
    elif capability:
        capability = capability.lower()
        
        # Notion関連の機能
        notion_capabilities = [
            "store data", "save recipe", "register recipe", "database", 
            "notion", "store in notion", "save to database"
        ]
        
        # データ検証関連の機能
        validation_capabilities = [
            "validate", "validation", "check data", "verify", 
            "preprocess", "data validation"
        ]
        
        # レシピ関連の機能
        recipe_capabilities = [
            "recipe", "cooking", "food", "ingredients", 
            "recipe database", "recipe management"
        ]
        
        # 能力のマッチング
        if any(cap in capability for cap in notion_capabilities):
            return jsonify({
                "available": True,
                "details": {
                    "capability": "notion_integration",
                    "description": "Can store and manage data in Notion databases",
                    "inputFormat": "JSON object with structured data"
                }
            })
        elif any(cap in capability for cap in validation_capabilities):
            return jsonify({
                "available": True,
                "details": {
                    "capability": "data_validation",
                    "description": "Can validate and preprocess structured data",
                    "inputFormat": "JSON object with data to validate"
                }
            })
        elif any(cap in capability for cap in recipe_capabilities):
            return jsonify({
                "available": True,
                "details": {
                    "capability": "recipe_management",
                    "description": "Can store and manage recipe information in databases",
                    "inputFormat": "JSON object with recipe data"
                }
            })
        # コンテンツタイプ処理能力
        elif "content_type" in capability:
            if "recipe" in capability:
                return jsonify({
                    "available": True,
                    "details": {
                        "contentType": "recipe",
                        "processingCapabilities": ["storage", "organization"]
                    }
                })
        
        # デフォルトの応答
        return jsonify({"available": False})
    
    # どちらも指定されていない場合 (エラー)
    return jsonify({
        "available": False,
        "error": "Unsupported query format. Use 'skill' or 'capability' parameter."
    }), 400

@app.route('/validate-data', methods=['POST'])
def validate_data():
    """
    レシピデータを検証し前処理するエンドポイント
    """
    if not request.is_json:
        logger.error("Request is not JSON")
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    recipe_data = data.get('data')
    
    if not recipe_data:
        return jsonify({
            "status": "error",
            "message": "Missing 'data' parameter in request."
        }), 400
    
    validated_data, errors = validate_and_preprocess_recipe_data(recipe_data)
    
    if validated_data is None:
        # 致命的なエラーがある場合
        return jsonify({
            "status": "error",
            "errors": errors,
            "data": None
        }), 400
    
    return jsonify({
        "status": "success" if not errors else "warning",
        "warnings": errors,  # エラーは警告として扱う
        "data": validated_data
    }), 200

@app.route('/tasks/send', methods=['POST'])
def tasks_send():
    """
    タスクを受け付け、レシピ情報をNotionに登録する
    """
    if not request.is_json:
        logger.error("Request is not JSON")
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    task_id = data.get('taskId') or str(uuid.uuid4())
    message = data.get('message')
    
    # 受信したメタデータを取得
    metadata = data.get('metadata', {})
    youtube_url = metadata.get('youtube_url', '')
    channel_name = metadata.get('channel_name', '')
    thumbnail_url = metadata.get('thumbnail_url', '')
    
    logger.info(f"[{task_id}] 新しいタスクを受信しました。メタデータ: {metadata}")
    logger.debug(f"[{task_id}] リクエストデータ: {data}")

    # messageからレシピ情報JSONを抽出
    recipe_data = None
    if message and isinstance(message.get('parts'), list):
         for part in message['parts']:
             mime_type = part.get('mimeType')
             logger.debug(f"[{task_id}] mimeType: {mime_type} のパートを処理中")
             # application/json の DataPart を優先
             if mime_type == 'application/json' and 'data' in part:
                 if isinstance(part['data'], dict):
                      recipe_data = part['data']
                      logger.info(f"[{task_id}] JSONデータパートからレシピデータを抽出しました")
                      break
             # application/json の TextPart も考慮
             elif mime_type == 'application/json' and 'text' in part:
                 try:
                     recipe_data = json.loads(part['text'])
                     if isinstance(recipe_data, dict):
                          logger.info(f"[{task_id}] JSONテキストパートからレシピデータを抽出しました")
                          break
                     else:
                          logger.warning(f"[{task_id}] JSONテキストパートの内容が辞書形式ではありません")
                          recipe_data = None
                 except json.JSONDecodeError as e:
                     logger.warning(f"[{task_id}] JSONテキストパートのパース失敗: {e}")
                     recipe_data = None

    # 必須情報のチェック (レシピデータが辞書形式であるか)
    if not recipe_data or not isinstance(recipe_data, dict):
        logger.error(f"[{task_id}] リクエストから有効なレシピデータを取得できませんでした")
        return jsonify({
            "taskId": task_id,
            "status": "failed",
            "error": {"code": "BadRequest", "message": "メッセージパーツに有効なレシピデータ(application/json)がありません"}
        }), 400

    # メタデータをレシピデータに追加
    if youtube_url and "youtube_url" not in recipe_data:
        recipe_data["youtube_url"] = youtube_url
        logger.info(f"[{task_id}] メタデータからYouTube URLを追加: {youtube_url}")
    
    if channel_name and "channel_name" not in recipe_data:
        recipe_data["channel_name"] = channel_name
        logger.info(f"[{task_id}] メタデータからチャンネル名を追加: {channel_name}")
    
    if thumbnail_url and "thumbnail_url" not in recipe_data:
        recipe_data["thumbnail_url"] = thumbnail_url
        logger.info(f"[{task_id}] メタデータからサムネイルURLを追加: {thumbnail_url}")

    # データの検証と前処理を実行
    validated_data, validation_errors = validate_and_preprocess_recipe_data(recipe_data)
    if validation_errors:
        logger.warning(f"[{task_id}] データ検証で警告が発生: {validation_errors}")
    
    # 致命的なエラーがある場合はここで処理を中断
    if validated_data is None:
        logger.error(f"[{task_id}] データ検証で致命的なエラーが発生: {validation_errors}")
        return jsonify({
            "taskId": task_id,
            "status": "failed",
            "error": {"code": "ValidationFailed", "message": validation_errors[0] if validation_errors else "データ検証に失敗しました"}
        }), 400
    
    # 検証済みデータを使用
    recipe_data = validated_data
    
    logger.info(f"[{task_id}] Notion登録処理を開始します: {list(recipe_data.keys())}")

    # === Notion登録処理を実行 ===
    page_url = None
    error_message = None
    task_status = "working" # 初期状態

    try:
        logger.info(f"[{task_id}] add_recipe_to_notion関数を呼び出し中...")
        page_url = add_recipe_to_notion(recipe_data)
        if page_url:
            task_status = "completed"
            logger.info(f"[{task_id}] Notionページの作成に成功しました: {page_url}")
        else:
            # add_recipe_to_notion が None を返した場合 (内部でエラーログ出力済)
            task_status = "failed"
            error_message = "Notionへのレシピ追加に失敗しました。詳細はエージェントのログを確認してください。"
            logger.error(f"[{task_id}] add_recipe_to_notionがNoneを返しました")

    except Exception as e:
        # add_recipe_to_notion 呼び出し自体で予期せぬエラーが発生した場合
        logger.exception(f"[{task_id}] Notion処理中に予期せぬエラーが発生: {e}")
        task_status = "failed"
        error_message = f"Notion処理中に予期せぬエラーが発生しました: {e}"

    logger.info(f"[{task_id}] タスクのステータス: '{task_status}'")

    # A2Aプロトコルに準拠したレスポンスを構築
    response = {
        "taskId": task_id,
        "status": task_status,
        "metadata": {
            "flow_step": "completed",  # 最終ステップ完了
            "flow_completed": True,    # エンドツーエンドフロー完了
            "youtube_url": recipe_data.get("youtube_url", ""),
            "channel_name": recipe_data.get("channel_name", ""),
            "thumbnail_url": recipe_data.get("thumbnail_url", ""),
            "recipe_name": recipe_data.get("recipe_name", "不明なレシピ")
        }
    }
    
    # タスク完了時
    if task_status == "completed" and page_url:
        # NotionページURLをメタデータに追加
        response["metadata"]["notion_url"] = page_url
        
        # アーティファクトを追加
        response["artifacts"] = [
            {
                "type": "notion_page",  # アーティファクトタイプを明示
                "parts": [
                    {
                        "text": page_url,
                        "mimeType": "text/uri-list"
                    }
                ]
            }
        ]
    
    # エラー発生時
    if error_message:
        response["error"] = {
            "code": "ProcessingFailed",
            "message": error_message
        }
    
    logger.info(f"[{task_id}] A2Aプロトコル準拠のレスポンスを返します")
    return jsonify(response)

@app.route('/health', methods=['GET'])
def health_check():
    """簡単なヘルスチェック用エンドポイント"""
    return jsonify({"status": "ok"})

#----------------------------------------------
# 5. A2A連携機能（エージェント探索・通信）
#----------------------------------------------
def discover_agents(skill=None, capability=None, content_type=None):
    """利用可能なエージェントを発見する（Agent Discovery）
    
    Args:
        skill: 特定のスキル名で検索（例: "recipe_extraction"）
        capability: より一般的な能力の説明（例: "extract recipe from text"）
        content_type: 処理するコンテンツタイプ（例: "youtube", "recipe"）
        
    Returns:
        発見されたエージェントのリスト
    """
    # 環境に応じてエージェントのURLを設定
    # Docker環境ではサービス名、それ以外ではlocalhostを使用
    is_docker = os.environ.get('DOCKER_ENV', '').lower() == 'true'
    
    if is_docker:
        # Docker環境
        known_agents = [
            "http://youtube-agent:5000",     # YouTube処理エージェント（サービス名を修正）
            "http://recipe-extractor:5001"   # レシピ抽出エージェント
        ]
    else:
        # 通常環境
        known_agents = [
            "http://localhost:5000",  # YouTube処理エージェント
            "http://localhost:5001"   # レシピ抽出エージェント
        ]
    
    # Docker環境でlocalhostをサービス名に変換するためのマッピング
    docker_url_mapping = {
        "http://localhost:5000": "http://youtube-agent:5000",
        "http://localhost:5001": "http://recipe-extractor:5001",
        "http://localhost:5002": "http://notion-agent:5002"
    }
    
    discovered_agents = []
    
    for agent_base_url in known_agents:
        try:
            # Agent Cardを取得
            agent_card_url = f"{agent_base_url}/.well-known/agent.json"
            logger.info(f"🔍 エージェント探索: {agent_card_url} に接続を試みています...")
            response = requests.get(agent_card_url, timeout=5)
            
            if response.status_code == 200:
                agent_card = response.json()
                agent_meets_criteria = True
                
                # エージェントカードから取得したURLをDocker環境では適切に変換
                agent_url = agent_card.get("url", agent_base_url)
                if is_docker and agent_url.startswith("http://localhost:"):
                    port = agent_url.split(":")[-1]
                    docker_url = docker_url_mapping.get(agent_url)
                    if docker_url:
                        logger.info(f"🔄 Docker環境のため、URLを変換: {agent_url} → {docker_url}")
                        agent_url = docker_url
                    else:
                        # ポート番号から推測する
                        if port == "5000":
                            agent_url = "http://youtube-agent:5000"
                        elif port == "5001":
                            agent_url = "http://recipe-extractor:5001"
                        elif port == "5002":
                            agent_url = "http://notion-agent:5002"
                        logger.info(f"🔄 Docker環境のため、URLをポート番号から推測して変換: {agent_url}")
                
                agent_info = {
                    "url": agent_url,  # 変換されたURLを使用
                    "name": agent_card.get("name", "Unknown Agent"),
                    "skills": [s.get("name") for s in agent_card.get("skills", [])],
                    "agent_card": agent_card
                }
                
                # スキルが指定されていて、そのスキルを持っていない場合はスキップ
                if skill:
                    has_skill = False
                    # エージェントカードからのスキル検索
                    if any(skill.lower() in s.lower() or s.lower() in skill.lower() for s in agent_info["skills"]):
                        has_skill = True
                    
                    # QuerySkill機能を試す
                    if not has_skill:
                        try:
                            if not query_agent_skill(agent_base_url, skill):
                                agent_meets_criteria = False
                            else:
                                has_skill = True
                        except Exception as e:
                            logger.debug(f"QuerySkill試行中にエラー: {e}")
                            agent_meets_criteria = False
                
                # 能力指定の場合
                if capability and agent_meets_criteria:
                    try:
                        if not query_agent_capability(agent_base_url, capability):
                            agent_meets_criteria = False
                    except Exception as e:
                        logger.debug(f"Capability確認中にエラー: {e}")
                        agent_meets_criteria = False
                
                # コンテンツタイプが指定されている場合
                if content_type and agent_meets_criteria:
                    try:
                        if not can_handle_content(agent_base_url, content_type):
                            agent_meets_criteria = False
                    except Exception as e:
                        logger.debug(f"コンテンツタイプ確認中にエラー: {e}")
                        agent_meets_criteria = False
                
                if agent_meets_criteria:
                    discovered_agents.append(agent_info)
                    logger.info(f"🔍 エージェント発見: {agent_info['name']} at {agent_url}")
        except Exception as e:
            logger.warning(f"⚠️ エージェント探索エラー ({agent_base_url}): {e}")
    
    return discovered_agents

def query_agent_skill(agent_url, skill_name):
    """エージェントが特定のスキルを持っているか確認する

    Args:
        agent_url: エージェントのベースURL
        skill_name: 確認するスキル名
    
    Returns:
        bool: スキルが利用可能ならTrue
    """
    # Docker環境でlocalhostをサービス名に変換
    if os.environ.get('DOCKER_ENV', '').lower() == 'true' and agent_url.startswith("http://localhost:"):
        port = agent_url.split(":")[-1]
        if port == "5000":
            agent_url = "http://youtube-agent:5000"
        elif port == "5001":
            agent_url = "http://recipe-extractor:5001"
        elif port == "5002":
            agent_url = "http://notion-agent:5002"
    
    try:
        query_url = f"{agent_url}/query-skill"
        response = requests.post(
            query_url,
            json={"skill": skill_name},
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("available", False)
        return False
    except Exception as e:
        logger.error(f"⚠️ QuerySkill呼び出しエラー ({agent_url}): {e}")
        return False

def query_agent_capability(agent_url, capability_description):
    """エージェントが特定の能力（より一般的な説明）を持っているか確認

    Args:
        agent_url: エージェントのベースURL
        capability_description: 能力の説明（例: "transcribe youtube videos"）
    
    Returns:
        bool: 能力があるとエージェントが判断したらTrue
    """
    # Docker環境でlocalhostをサービス名に変換
    if os.environ.get('DOCKER_ENV', '').lower() == 'true' and agent_url.startswith("http://localhost:"):
        port = agent_url.split(":")[-1]
        if port == "5000":
            agent_url = "http://youtube-agent:5000"
        elif port == "5001":
            agent_url = "http://recipe-extractor:5001"
        elif port == "5002":
            agent_url = "http://notion-agent:5002"
    
    try:
        # 現段階ではQuerySkillエンドポイントを使用
        query_url = f"{agent_url}/query-skill"
        response = requests.post(
            query_url,
            json={"capability": capability_description},
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("available", False)
        return False
    except Exception:
        return False

def can_handle_content(agent_url, content_type):
    """エージェントが特定のコンテンツタイプを処理できるか確認
    
    Args:
        agent_url: エージェントのベースURL
        content_type: コンテンツのタイプ（例: "youtube", "recipe"）
    
    Returns:
        bool: 処理可能ならTrue
    """
    # 現段階ではQuerySkillを使用
    return query_agent_capability(agent_url, f"process {content_type} content")

#----------------------------------------------
# 6. データ処理とバリデーション関連
#----------------------------------------------
def validate_and_preprocess_recipe_data(recipe_data):
    """
    レシピデータの検証と前処理を行う
    
    Args:
        recipe_data (dict): 検証・前処理するレシピデータ
        
    Returns:
        tuple: (validated_data, errors)
            - validated_data (dict): 検証・前処理済みのデータ (エラーがある場合はNone)
            - errors (list): エラーメッセージのリスト (エラーがない場合は空リスト)
    """
    if not recipe_data or not isinstance(recipe_data, dict):
        return None, ["Invalid data format: Recipe data must be a JSON object"]
    
    errors = []
    
    # 必須フィールドの検証
    required_fields = ["recipe_name", "ingredients", "instructions"]
    missing_fields = [field for field in required_fields if field not in recipe_data]
    
    if missing_fields:
        errors.append(f"Missing required fields: {', '.join(missing_fields)}")
    
    # データの深いコピーを作成
    validated_data = copy.deepcopy(recipe_data)
    
    # フィールドの検証と前処理
    if "recipe_name" in validated_data:
        if not validated_data["recipe_name"] or not isinstance(validated_data["recipe_name"], str):
            validated_data["recipe_name"] = "不明なレシピ"
            errors.append("Invalid recipe_name: using default value")
    
    if "ingredients" in validated_data:
        ingredients = validated_data["ingredients"]
        # 材料リストを標準化
        if isinstance(ingredients, str):
            # 文字列の場合は行ごとにリスト化
            validated_data["ingredients"] = [line.strip() for line in ingredients.split("\n") if line.strip()]
        elif not isinstance(ingredients, list):
            validated_data["ingredients"] = []
            errors.append("Invalid ingredients format: must be a list or string")
        else:
            # リストの場合は空の要素を削除
            validated_data["ingredients"] = [str(item) for item in ingredients if item]
    
    if "instructions" in validated_data:
        instructions = validated_data["instructions"]
        # 手順を標準化
        if isinstance(instructions, str):
            # 文字列の場合は行ごとにリスト化
            validated_data["instructions"] = [line.strip() for line in instructions.split("\n") if line.strip()]
        elif not isinstance(instructions, list):
            validated_data["instructions"] = []
            errors.append("Invalid instructions format: must be a list or string")
        else:
            # リストの場合は空の要素を削除し、数字がない場合は追加
            processed_instructions = []
            for i, item in enumerate([str(inst) for inst in instructions if inst]):
                # 既に番号付けされているかチェック
                if not item.strip().startswith(f"{i+1}.") and not item.strip()[0:2].isdigit():
                    processed_instructions.append(f"{i+1}. {item}")
                else:
                    processed_instructions.append(item)
            validated_data["instructions"] = processed_instructions
    
    # YouTube URLの検証
    if "youtube_url" in validated_data:
        url = validated_data["youtube_url"]
        if not url or not isinstance(url, str) or not ("youtube.com" in url or "youtu.be" in url):
            errors.append("Invalid YouTube URL format")
    
    # エラーがなければ検証済みデータを返す、あれば元のデータと警告を返す
    if errors and len(missing_fields) < len(required_fields):  # 一部のフィールドだけが欠けている場合
        logger.warning(f"データ検証で警告が発生: {errors}")
        return validated_data, errors
    elif errors:  # 致命的なエラーがある場合
        logger.error(f"データ検証で致命的なエラーが発生: {errors}")
        return None, errors
    
    return validated_data, []

#----------------------------------------------
# 7. メインアプリケーション実行
#----------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    logger.info(f"Starting Notion Agent server on port {port}")
    serve(app, host='0.0.0.0', port=port)
