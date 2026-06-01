# ファイル名: agents/recipe_agent/main.py
# 説明: YouTube文字起こしテキストからレシピ情報を抽出するエージェント

#----------------------------------------------
# 1. インポート
#----------------------------------------------
# 標準ライブラリ
import os
import json
import uuid
import logging
import socket
from pathlib import Path

# サードパーティライブラリ
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from waitress import serve

# 自作モジュール
from recipe_extractor import extract_recipe_from_text

#----------------------------------------------
# 2. 定数と設定
#----------------------------------------------
# レシピ抽出エージェント用のAgent Cardパス
AGENT_CARD_PATH = Path(__file__).parent / "agent_card.json"
# デフォルトポート (既存エージェントと衝突しないように設定)
DEFAULT_PORT = 5001

#----------------------------------------------
# 3. Flask初期化とロギング設定
#----------------------------------------------
# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flaskアプリケーション初期化
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

#----------------------------------------------
# 4. API関連の関数（エンドポイント）
#----------------------------------------------
@app.route('/.well-known/agent.json', methods=['GET'])
def get_agent_card():
    """
    Agent Cardを提供する
    
    Returns:
        dict: エージェントカード情報のJSONレスポンス
    """
    # Docker Compose環境などを考慮し、リクエストヘッダーからHostを取得試行
    host_url = request.host_url.rstrip('/')
    # 環境変数で上書き可能にする（より堅牢）
    server_base_url = os.environ.get('A2A_SERVER_URL', host_url)
    if not server_base_url:
         server_base_url = f"http://localhost:{DEFAULT_PORT}"  # フォールバック
         logger.warning(f"サーバーURLをリクエストまたは環境変数から取得できませんでした。代替値を使用します: {server_base_url}")

    try:
        with open(AGENT_CARD_PATH, 'r', encoding='utf-8') as f:
            agent_card = json.load(f)
            # URLを動的に設定
            agent_card["url"] = server_base_url
        return jsonify(agent_card)
    except FileNotFoundError as e:
        logger.error(f"エージェントカードファイルが見つかりません: {AGENT_CARD_PATH}, エラー: {e}")
        return jsonify({"error": "エージェントカードファイルが見つかりません"}), 404
    except json.JSONDecodeError as e:
        logger.error(f"エージェントカードファイルのJSON形式が不正です: {AGENT_CARD_PATH}, エラー: {e}")
        return jsonify({"error": "エージェントカードファイルのJSON形式が不正です"}), 500
    except Exception as e:
        logger.error(f"エージェントカードの読み込み中に予期せぬエラーが発生しました: {e}")
        return jsonify({"error": "エージェントカードの読み込みに失敗しました"}), 500

@app.route('/query-skill', methods=['POST'])
def query_skill():
    """
    エージェントが特定のスキルを持っているか確認するエンドポイント (A2A拡張)
    
    JSON形式の例:
    リクエスト: {"skill": "recipe_extraction"} または {"capability": "extract recipe from text"}
    
    Returns:
        dict: スキル利用可否情報のJSONレスポンス
    """
    if not request.is_json:
        return jsonify({"error": "リクエストはJSON形式である必要があります"}), 400
    
    data = request.get_json()
    
    # スキル名による照会
    if "skill" in data:
        skill_name = data["skill"].lower()
        
        # サポートしているスキル
        supported_skills = {
            "recipe_extraction": {
                "available": True,
                "details": {
                    "inputFormat": "Text containing recipe information",
                    "outputFormat": "Structured recipe data in JSON format",
                    "supportedLanguages": ["ja", "en"],
                    "canProcess": ["ingredients", "instructions", "cookingTime", "servingSize"]
                }
            },
            "recipe": {
                "available": True,
                "details": {
                    "inputFormat": "Text containing recipe information",
                    "outputFormat": "Structured recipe data in JSON format"
                }
            },
            "notion_registration": {
                "available": False
            }
        }
        
        # スキル名の部分一致も許容
        for supported_skill, info in supported_skills.items():
            if skill_name in supported_skill or supported_skill in skill_name:
                return jsonify(info)
        
        # デフォルトの応答
        return jsonify({"available": False})
    
    # 能力（より一般的な説明）による照会
    elif "capability" in data:
        capability = data["capability"].lower()
        
        # レシピ関連の能力をサポート
        recipe_capabilities = [
            "extract recipe", "recipe extraction", "recipe parser",
            "parse recipe", "recipes", "cooking", "food"
        ]
        
        if any(cap in capability for cap in recipe_capabilities):
            return jsonify({
                "available": True,
                "details": {
                    "inputFormat": "Text containing recipe information",
                    "outputFormat": "Structured recipe data in JSON format",
                    "supportedCapabilities": recipe_capabilities
                }
            })
        
        # コンテンツタイプによる処理能力
        if "content_type" in capability:
            # レシピコンテンツに対応
            if "recipe" in capability:
                return jsonify({
                    "available": True,
                    "details": {
                        "contentType": "recipe",
                        "processingCapabilities": ["extraction", "structuring"]
                    }
                })
        
        # デフォルトの応答
        return jsonify({"available": False})
    
    # サポートされていないリクエスト形式
    return jsonify({
        "available": False,
        "error": "サポートされていないクエリ形式です。'skill'または'capability'パラメータを使用してください。"
    }), 400

@app.route('/tasks/send', methods=['POST'])
def tasks_send():
    """
    タスクを受け付け、文字起こしテキストからレシピを抽出する
    """
    if not request.is_json:
        return jsonify({"error": "リクエストはJSON形式である必要があります"}), 400

    data = request.get_json()

    # タスクID取得
    task_id = data.get('taskId') or str(uuid.uuid4())
    message = data.get('message')
    
    # 受信したメタデータを取得
    metadata = data.get('metadata', {})
    youtube_url = metadata.get('youtube_url', '')
    channel_name = metadata.get('channel_name', '')
    thumbnail_url = metadata.get('thumbnail_url', '')
    video_title = metadata.get('video_title', '')

    logger.info(f"[{task_id}] 新しいタスクを受信しました。メタデータ: {metadata}")

    # messageからレシピ情報JSONを抽出
    transcript_text = None
    
    if message and isinstance(message.get('parts'), list):
        message_parts = message['parts']
        
        # 文字起こしテキストの取得
        for part in message_parts:
            # mimeTypeによる取得
            if part.get('mimeType') == 'text/plain' and 'text' in part:
                transcript_text = part['text']
            # typeフィールドによる取得（A2A標準）
            elif part.get('type') == 'text' and 'text' in part:
                transcript_text = part['text']
            # キー名での直接取得
            elif 'transcript_text' in part:
                transcript_text = part['transcript_text']
            # textのみの場合
            elif 'text' in part:
                transcript_text = part['text']
            
            if transcript_text:
                break
        
        # YouTube URLがメタデータにない場合はメッセージから取得
        if not youtube_url:
            for part in message_parts:
                # mimeTypeによる取得
                if part.get('mimeType') == 'text/uri-list' and ('uri' in part or 'text' in part):
                    youtube_url = part.get('uri') or part.get('text')
                # データオブジェクト内のyoutube_url
                elif isinstance(part.get('data'), dict) and 'youtube_url' in part['data']:
                    youtube_url = part['data']['youtube_url']
                    
                    # データオブジェクト内にチャンネル名とサムネイルURLも含まれる可能性がある
                    if not channel_name and 'channel_name' in part['data']:
                        channel_name = part['data']['channel_name']
                    if not thumbnail_url and 'thumbnail_url' in part['data']:
                        thumbnail_url = part['data']['thumbnail_url']
                
                if youtube_url:
                    break
        
        # メタデータをさらに探索 (別のパートに含まれている可能性)
        if not channel_name or not thumbnail_url:
            for part in message_parts:
                if isinstance(part.get('data'), dict):
                    if not channel_name and 'channel_name' in part['data']:
                        channel_name = part['data']['channel_name']
                        logger.info(f"[{task_id}] チャンネル名をデータパートから取得: {channel_name}")
                    
                    if not thumbnail_url and 'thumbnail_url' in part['data']:
                        thumbnail_url = part['data']['thumbnail_url']
                        logger.info(f"[{task_id}] サムネイルURLをデータパートから取得: {thumbnail_url}")

    # 必須情報のチェック
    if not transcript_text or not youtube_url:
        missing = []
        if not transcript_text: missing.append("transcript text (text/plain)")
        if not youtube_url: missing.append("youtube_url (text/uri-list or data)")
        error_response = {
            "taskId": task_id,
            "status": "failed",
            "error": {"code": "BadRequest", "message": f"メッセージパーツに必要な情報が不足しています: {', '.join(missing)}。"}
        }
        logger.error(f"エラー: {error_response}")
        return jsonify(error_response), 400

    logger.info(f"[{task_id}] URL: {youtube_url} のレシピ抽出タスクを受信しました")
    if channel_name:
        logger.info(f"[{task_id}] チャンネル名: {channel_name}")
    if thumbnail_url:
        logger.info(f"[{task_id}] サムネイルURL: {thumbnail_url[:50]}...")

    # --- レシピ抽出処理を実行 ---
    extracted_recipe_json = None
    error_message = None
    task_status = "working" # 初期状態

    try:
        extracted_recipe_json = extract_recipe_from_text(transcript_text, youtube_url, channel_name, thumbnail_url, video_title)
        if extracted_recipe_json:
            # JSONとしてパースし、必須フィールドが含まれているか検証
            try:
                parsed_json = json.loads(extracted_recipe_json)
                required_fields = ["recipe_name", "youtube_url", "category", "ingredients", "instructions"]
                missing_fields = [field for field in required_fields if field not in parsed_json]
                
                if missing_fields:
                    logger.warning(f"[{task_id}] 抽出されたJSONに必須フィールドが不足しています: {', '.join(missing_fields)}")
                    # デフォルト値で補完
                    if "recipe_name" not in parsed_json:
                        parsed_json["recipe_name"] = "不明なレシピ"
                        logger.warning(f"[{task_id}] recipe_nameにデフォルト値を設定しました")
                    
                    if "youtube_url" not in parsed_json:
                        parsed_json["youtube_url"] = youtube_url
                        logger.warning(f"[{task_id}] youtube_urlを追加しました")
                
                # YouTubeメタデータの保証
                if channel_name and not parsed_json.get("channel_name"):
                    parsed_json["channel_name"] = channel_name
                    logger.info(f"[{task_id}] channel_nameを追加しました: {channel_name}")
                
                if thumbnail_url and not parsed_json.get("thumbnail_url"):
                    parsed_json["thumbnail_url"] = thumbnail_url
                    logger.info(f"[{task_id}] thumbnail_urlを追加しました")
                
                # 再度JSONに変換
                extracted_recipe_json = json.dumps(parsed_json, ensure_ascii=False)
                
                # 材料リストの形式確認（Notionエージェント向け）
                if "ingredients" in parsed_json and parsed_json["ingredients"]:
                    if not all(isinstance(ing, str) for ing in parsed_json["ingredients"]):
                        logger.warning(f"[{task_id}] 材料リストの形式が期待と異なります（文字列配列ではありません）")
                
                # タスク完了後に次のエージェントに転送
                notion_url = None
                send_result = send_to_next_agent(task_id, extracted_recipe_json, youtube_url, channel_name, thumbnail_url)
                if not send_result:
                    task_status = "failed"
                    error_message = "Notionエージェントへの転送に失敗しました"
                    logger.error(f"[{task_id}] {error_message}")
                elif send_result.get("status") == "failed":
                    task_status = "failed"
                    error_message = send_result.get("error", {}).get("message", "Notion登録に失敗しました")
                    logger.error(f"[{task_id}] Notionエージェントがエラーを返しました: {error_message}")
                else:
                    task_status = "completed"
                    notion_url = send_result.get("metadata", {}).get("notion_url")
                    if notion_url:
                        logger.info(f"[{task_id}] NotionページURL: {notion_url}")
                
            except json.JSONDecodeError:
                logger.error(f"[{task_id}] 抽出されたJSONがパースできませんでした")
                task_status = "failed"
                error_message = "Failed to parse extracted recipe JSON."
        else:
            # extract_recipe_from_text が None を返した場合 (内部でエラーログ出力済)
            task_status = "failed"
            error_message = "Failed to extract recipe from text using LLM."

    except Exception as e:
        # extract_recipe_from_text 呼び出し自体で予期せぬエラーが発生した場合
        logger.error(f"[{task_id}] レシピ抽出呼び出し中に予期せぬエラーが発生しました: {e}")
        task_status = "failed"
        error_message = f"予期せぬエラーが発生しました: {e}"

    logger.info(f"[{task_id}] タスクがステータス '{task_status}' で完了しました。")

    # A2Aプロトコルに準拠した返信を作成
    response = {
        "taskId": task_id,
        "status": task_status,
        "metadata": {
            "flow_step": "completed" if task_status == "completed" else "failed",
            "flow_completed": task_status == "completed",
            "youtube_url": youtube_url,
            "channel_name": channel_name,
            "thumbnail_url": thumbnail_url,
            "source_agent": "recipe_agent"
        }
    }
    if task_status == "completed" and notion_url:
        response["metadata"]["notion_url"] = notion_url
    
    # タスクが完了した場合のみアーティファクトを含める
    if task_status == "completed":
        recipe_data = json.loads(extracted_recipe_json)
        response["artifacts"] = [
            {
                "type": "recipe_data", # アーティファクトタイプを明示的に設定
                "parts": [
                    {
                        "mimeType": "application/json",
                        "data": recipe_data
                    }
                ]
            }
        ]
    
    # エラーがある場合はエラー情報を含める
    if error_message:
        response["error"] = {
            "code": "ProcessingError",
            "message": error_message
        }
    
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
        skill: 特定のスキル名で検索（例: "notion"）
        capability: より一般的な能力の説明（例: "store recipe in database"）
        content_type: 処理するコンテンツの種類（例: "database", "recipe"）
        
    Returns:
        発見されたエージェントのリスト
    """
    # 環境に応じてエージェントのURLを設定
    # Docker環境判定の改善: 環境変数またはネットワーク検出
    is_docker = False
    
    # 環境変数による判定
    if os.environ.get('DOCKER_ENV', '').lower() == 'true':
        is_docker = True
    
    # ホスト名解決による判定を追加
    if not is_docker:
        try:
            # Docker環境では'agent'というホスト名が解決できるはず
            socket.gethostbyname('agent')
            is_docker = True
            logger.info("Docker環境を検出しました (ホスト名解決から)")
        except:
            pass
    
    # コンテナIDの存在確認による判定
    if not is_docker and os.path.exists('/.dockerenv'):
        is_docker = True
        logger.info("Docker環境を検出しました (/.dockerenv の存在から)")
    
    if is_docker:
        logger.info("Docker環境で実行中 - コンテナ名をホストとして使用します")
        # Docker環境（コンテナ名を使用）
        known_agents = [
            "http://youtube-agent:5000",        # YouTube処理エージェント
            "http://notion-agent:5002"  # Notion連携エージェント
        ]
    else:
        logger.info("ローカル環境で実行中 - localhostを使用します")
        # 通常環境（localhostを使用）
        known_agents = [
            "http://localhost:5000",  # YouTube処理エージェント
            "http://localhost:5002"   # Notion連携エージェント
        ]
    
    discovered_agents = []
    
    for agent_base_url in known_agents:
        try:
            # Agent Cardを取得
            agent_card_url = f"{agent_base_url}/.well-known/agent.json"
            logger.info(f"エージェントカードの取得を試みています: {agent_card_url}")
            response = requests.get(agent_card_url, timeout=5)
            
            if response.status_code == 200:
                agent_card = response.json()
                agent_meets_criteria = True
                
                # スキルが指定されていて、そのスキルを持っていない場合はスキップ
                if skill:
                    has_skill = False
                    for agent_skill in agent_card.get("skills", []):
                        if skill.lower() in agent_skill.get("name", "").lower():
                            has_skill = True
                            break
                    
                    if not has_skill:
                        # QuerySkill機能を試す
                        try:
                            if not query_agent_skill(agent_base_url, skill):
                                agent_meets_criteria = False
                            else:
                                has_skill = True
                        except Exception as e:
                            logger.debug(f"QuerySkill試行中にエラー: {e}")
                            agent_meets_criteria = False
                    
                # 能力(capability)が指定されている場合
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
                    discovered_agents.append({
                        "url": agent_card.get("url", agent_base_url),
                        "name": agent_card.get("name", "Unknown Agent"),
                        "skills": [s.get("name") for s in agent_card.get("skills", [])],
                        "agent_card": agent_card
                    })
                    logger.info(f"🔍 エージェント発見: {agent_card.get('name')} at {agent_base_url}")
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
        capability_description: 能力の説明（例: "store recipe in database"）
    
    Returns:
        bool: 能力があるとエージェントが判断したらTrue
    """
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
        content_type: コンテンツのタイプ（例: "recipe", "database"）
    
    Returns:
        bool: 処理可能ならTrue
    """
    # 現段階ではQuerySkillを使用
    return query_agent_capability(agent_url, f"process {content_type} content")

def analyze_content_type(recipe_json):
    """レシピJSONからコンテンツタイプを推定する
    
    Args:
        recipe_json: 分析するレシピJSON
    
    Returns:
        string: 推定されたコンテンツタイプ
    """
    # レシピエージェントの場合、レシピデータをデータベースに保存するようなエージェントを探す
    return "database"

def send_to_next_agent(task_id, recipe_json, youtube_url=None, channel_name=None, thumbnail_url=None):
    """次のエージェントにタスクを送信する - A2A自律連携実装
    
    レシピデータの分析に基づいて適切なエージェントを動的に選択し、
    処理を次のエージェントに委託します。
    """
    # レシピデータをパース
    recipe_data = json.loads(recipe_json)
    
    # 必要なメタデータを確保
    if youtube_url is None and "youtube_url" in recipe_data:
        youtube_url = recipe_data["youtube_url"]
    
    if channel_name is None and "channel_name" in recipe_data:
        channel_name = recipe_data["channel_name"]
    
    if thumbnail_url is None and "thumbnail_url" in recipe_data:
        thumbnail_url = recipe_data["thumbnail_url"]
    
    # 1. Notion連携が可能なエージェントを探す（A2A発見プロセス）
    logger.info(f"[{task_id}] 🔍 Notion連携が可能なエージェントを探しています...")
    discovered_agents = discover_agents(skill="notion")
    
    # Notionスキルのエージェントが見つからなければ、より一般的な能力で探す
    if not discovered_agents:
        logger.info(f"[{task_id}] 🔍 データベース保存能力を持つエージェントを探しています...")
        discovered_agents = discover_agents(capability="store recipe in database")
            
    # エージェントが見つからない場合
    if not discovered_agents:
        logger.error(f"[{task_id}] ❌ タスクを転送できるエージェントが見つかりませんでした")
        return False
    
    # 2. 最適なエージェントを選択（ここでは単純に最初のエージェントを使用）
    selected_agent = discovered_agents[0]
    agent_url = selected_agent["url"]
    tasks_endpoint = f"{agent_url}/tasks/send"
    
    logger.info(f"[{task_id}] 🔄 タスクの転送先として '{selected_agent['name']}' が選択されました")
    
    # 3. タスクデータの構築 - A2Aプロトコルに準拠
    task_data = {
        "taskId": task_id,  # 同じタスクIDを維持
        "metadata": {
            "flow_step": "notion",  # 次のステップを指定
            "flow_completed": False,  # フローはまだ完了していない
            "youtube_url": youtube_url,
            "channel_name": channel_name,
            "thumbnail_url": thumbnail_url,
            "source_agent": "recipe_agent"
        },
        "message": {
            "parts": [
                {
                    "mimeType": "application/json",
                    "data": recipe_data
                }
            ]
        }
    }
    
    # 4. 次のエージェントにタスクを転送
    try:
        logger.info(f"[{task_id}] 🔄 '{selected_agent['name']}'にタスクを転送中...")
        response = requests.post(tasks_endpoint, json=task_data, timeout=60)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"[{task_id}] ✅ '{selected_agent['name']}'がタスクを処理しました（ステータス: {result.get('status')}）")
            return result
        else:
            logger.warning(f"[{task_id}] ⚠️ '{selected_agent['name']}'からエラー応答: {response.status_code}")
            return {"status": "failed", "error": {"message": f"HTTPエラー: {response.status_code}"}}
    except Exception as e:
        logger.warning(f"[{task_id}] ⚠️ '{selected_agent['name']}'との通信エラー: {e}")
        return None

#----------------------------------------------
# 6. メインアプリケーション実行
#----------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    logger.info(f"Starting Recipe Agent server on port {port}")
    serve(app, host='0.0.0.0', port=port) 