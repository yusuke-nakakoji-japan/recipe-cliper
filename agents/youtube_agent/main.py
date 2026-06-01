# ファイル名: agents/youtube_agent/main.py
# 説明: YouTubeから動画の字幕を取得し、テキストに変換するエージェント

#----------------------------------------------
# 1. インポート
#----------------------------------------------
# 標準ライブラリ
import os
import re
import json
import uuid
import time
from pathlib import Path

# サードパーティライブラリ
import requests
from flask import Flask, request, jsonify
import yt_dlp
from waitress import serve
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled, VideoUnavailable

#----------------------------------------------
# 2. ロギング設定
#----------------------------------------------
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 外部ライブラリのログ抑制
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('yt_dlp').setLevel(logging.ERROR)

#----------------------------------------------
# 3. 定数と設定
#----------------------------------------------
# エージェント設定
AGENT_CARD_PATH = Path(__file__).parent / "agent_card.json"

# デフォルトポート (既存エージェントと衝突しないように設定)
DEFAULT_PORT = 5000

# 字幕設定
SUBTITLE_LANG = ["ja", "en"]  # 取得する字幕の優先言語 (先頭が最優先)

#----------------------------------------------
# 4. Flaskアプリケーション初期化
#----------------------------------------------
app = Flask(__name__)
app.logger.setLevel(logging.ERROR)

# タスク状態をメモリで管理
task_states = {}

#----------------------------------------------
# 5. グローバル初期化処理
#----------------------------------------------
logger.info("YouTube Agent を起動します。")

#----------------------------------------------
# 6. API関連の関数（エンドポイント）
#----------------------------------------------
@app.route('/.well-known/agent.json', methods=['GET'])
def get_agent_card():
    """
    Agent Cardを提供するエンドポイント (A2A標準)
    
    Returns:
        dict: Agent CardのJSONレスポンス
    """
    try:
        with open(AGENT_CARD_PATH, 'r', encoding='utf-8') as f:
            agent_card = json.load(f)
        # Docker実行時はコンテナ内からのURLになるため、環境変数などで外部URLを設定推奨
        # agent_card['serverUrl'] = os.environ.get('AGENT_EXTERNAL_URL', 'http://localhost:5000')
        return jsonify(agent_card)
    except FileNotFoundError:
        return jsonify({"error": "Agent Card not found"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid Agent Card format"}), 500

@app.route('/query-skill', methods=['POST'])
def query_skill():
    """
    エージェントが特定のスキルを持っているか確認するエンドポイント (A2A標準)
    
    Returns:
        dict: スキル対応状況のJSONレスポンス
    """
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
        
    data = request.get_json()
    skill_name = data.get('skill')
    capability = data.get('capability')
    
    # スキル名による検索
    if skill_name:
        skill_name = skill_name.lower()
        # YouTubeエージェントは動画処理とテキスト抽出に特化
        supported_skills = ['youtube', 'video', 'transcription', 'subtitle', 'text_extraction']
        
        skill_available = any(s in skill_name for s in supported_skills)
        if skill_available:
            return jsonify({
                "available": True,
                "details": {
                    "name": "youtube_processing",
                    "description": "YouTube video processing and text extraction",
                    "parameters": {
                        "youtube_url": "URL of the YouTube video to process"
                    }
                }
            })
    
    # より一般的な能力の説明による検索
    elif capability:
        capability = capability.lower()
        # YouTube関連の能力
        youtube_capabilities = ['youtube', 'video', 'download', 'transcribe', 'subtitle', 'extract text', 'audio']
        
        if any(cap in capability for cap in youtube_capabilities):
            return jsonify({
                "available": True,
                "details": {
                    "capability": "youtube_processing",
                    "description": "Can process YouTube videos, extract subtitles and transcribe audio"
                }
            })
    
    # デフォルトのレスポンス
    return jsonify({"available": False})

@app.route('/tasks/send', methods=['POST'])
def tasks_send():
    """
    タスクを受け付け、YouTube動画をダウンロード文字起こしを行う
    """
    start_time = time.time() # 処理時間計測開始
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    task_id = data.get('taskId')
    message = data.get('message')

    if not task_id:
        task_id = str(uuid.uuid4())

    youtube_url = None
    # message構造からURLを抽出 (DataPartを想定、TextPartにも対応するなら追記)
    if message and isinstance(message.get('parts'), list):
        for part in message['parts']:
            if isinstance(part.get('data'), dict) and 'youtube_url' in part['data']:
                youtube_url = part['data']['youtube_url']
                break
            # TextPartの単純なテキストがURLの場合 (簡易対応)
            elif 'text' in part and ("youtube.com" in part['text'] or "youtu.be" in part['text']):
                youtube_url = part['text']
                break

    if not youtube_url:
        return jsonify({
            "taskId": task_id,
            "status": "failed",
            "error": {"code": "BadRequest", "message": "Missing or invalid 'youtube_url' in message parts."}
        }), 400

    logger.info(f"[{task_id}] Received task (ID: {task_id})")  # Don't print the actual YouTube URL

    subtitle_text = ""
    final_text = ""
    error_message = None
    task_status = "working"
    channel_name = None
    thumbnail_url = None
    video_title = None

    try:
        # --- 0. まず動画の基本情報を取得 ---
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                # まず情報を取得（ログは抑制）
                info_dict = ydl.extract_info(youtube_url, download=False)
                
                # より多くのキーを試してチャンネル名を取得
                channel_name = (info_dict.get('uploader') or 
                               info_dict.get('channel') or 
                               info_dict.get('channel_name') or 
                               info_dict.get('uploader_name') or 
                               "不明")
                               
                # 動画タイトルを取得
                video_title = info_dict.get('title') or ""

                # サムネイルURLを取得
                thumbnail_url = info_dict.get('thumbnail') or ""
                if not thumbnail_url and info_dict.get('thumbnails'):
                    thumbnail_url = info_dict['thumbnails'][0].get('url', "")

                logger.info(f"[{task_id}] 動画タイトル: {video_title}")
                logger.info(f"[{task_id}] チャンネル名: {channel_name}")
                logger.info(f"[{task_id}] サムネイルURL: {thumbnail_url[:50]}..." if thumbnail_url and len(thumbnail_url) > 50 else f"[{task_id}] サムネイルURL: {thumbnail_url}")
        except Exception as e:
            logger.warning(f"[{task_id}] 動画情報の取得でエラーが発生しました: {str(e)}")
            # エラーがあってもプロセスは続行（メタデータは任意）
            
        # --- 1. 字幕取得 ---
        logger.info(f"[{task_id}] 処理を開始: {youtube_url}")
        logger.info(f"[{task_id}] YouTube字幕取得を試みています...")
        subtitle_text = download_subtitles(youtube_url, SUBTITLE_LANG)

        # --- 2. 結果の確認 ---
        if subtitle_text:
            final_text = subtitle_text
            logger.info(f"[{task_id}] 字幕を取得しました（{len(final_text)}文字）")
        else:
            error_message = "この動画には字幕がありません。字幕付きの動画をお試しください。"
            task_status = "failed"
            logger.error(f"[{task_id}] {error_message}")
        
        # --- 3. 結果の状態確認 ---
        if task_status != "failed" and final_text:
            task_status = "completed"
            logger.info(f"[{task_id}] タスク完了（処理時間: {time.time() - start_time:.2f}秒）")
            
            # その後、次のエージェントに転送
            metadata = {
                "channel_name": channel_name,
                "thumbnail_url": thumbnail_url,
                "video_title": video_title
            }
            
            # A2A連携のために次のエージェントにタスクを転送
            send_result = send_to_next_agent(task_id, youtube_url, final_text, metadata)
            if not send_result:
                logger.warning(f"[{task_id}] 次のエージェントへの転送に失敗しました")
                task_states[task_id] = {"status": "failed", "error": "次のエージェントへの転送に失敗しました"}
            elif send_result.get("status") == "failed":
                error_msg = send_result.get("error", {}).get("message", "下流エージェントでエラーが発生しました")
                logger.error(f"[{task_id}] 下流エージェントがエラーを返しました: {error_msg}")
                task_states[task_id] = {"status": "failed", "error": error_msg}
            else:
                notion_url = send_result.get("metadata", {}).get("notion_url")
                task_states[task_id] = {"status": "completed", "notion_url": notion_url}
        
        # --- 4. 最終的な結果を構築 ---
        # A2Aプロトコルに準拠した形式で結果を返す
        result = {
            "taskId": task_id,
            "status": task_status,
            "metadata": {
                "flow_step": "youtube",  # 現在のステップ
                "flow_completed": False,  # YouTube処理は完了したがエンドツーエンドフローはまだ
                "channel_name": channel_name,
                "thumbnail_url": thumbnail_url,
                "youtube_url": youtube_url,
                "processing_time_seconds": time.time() - start_time
            }
        }
        
        # タスクが完了した場合のみアーティファクトを含める
        if task_status == "completed":
            result["artifacts"] = [
                {
                    "type": "transcription",  # アーティファクトタイプを明示的に設定
                    "parts": [
                        {
                            "text": final_text,
                            "mimeType": "text/plain"
                        }
                    ]
                },
                {
                    "type": "metadata",  # メタデータ用のアーティファクト
                    "parts": [
                        {
                            "mimeType": "application/json",
                            "data": {
                                "youtube_url": youtube_url,
                                "channel_name": channel_name,
                                "thumbnail_url": thumbnail_url
                            }
                        }
                    ]
                }
            ]
        # エラーがある場合はエラー情報を含める
        elif error_message:
            result["error"] = {
                "code": "ProcessingError",
                "message": error_message
            }
            
        return jsonify(result)
        
    except Exception as e:
        # 予期せぬエラーの場合
        error_message = f"予期せぬエラーが発生しました: {str(e)}"
        logger.error(f"[{task_id}] {error_message}")
        
        return jsonify({
            "taskId": task_id,
            "status": "failed",
            "error": {
                "code": "InternalError",
                "message": error_message
            }
        }), 500

@app.route('/tasks/get', methods=['GET'])
def get_task():
    """
    タスクの現在の状態を取得する（A2Aプロトコル準拠）
    
    URLパラメータ:
        taskId: 照会するタスクのID
    
    Returns:
        Task: タスクオブジェクト（存在する場合）
    """
    task_id = request.args.get('taskId')
    
    if not task_id:
        return jsonify({
            "error": {
                "code": "BadRequest",
                "message": "taskIdパラメータが必要です"
            }
        }), 400
    
    stored = task_states.get(task_id)

    if stored is None:
        # まだ処理中（task_statesに登録されていない）
        return jsonify({
            "taskId": task_id,
            "status": "working",
            "metadata": {"flow_step": "processing", "flow_completed": False}
        })

    if stored["status"] == "failed":
        return jsonify({
            "taskId": task_id,
            "status": "failed",
            "metadata": {"flow_step": "failed", "flow_completed": False},
            "error": {"code": "ProcessingError", "message": stored.get("error", "エラーが発生しました")}
        })

    # completed
    metadata = {"flow_step": "completed", "flow_completed": True}
    if stored.get("notion_url"):
        metadata["notion_url"] = stored["notion_url"]

    logger.info(f"タスク状態の照会: {task_id} - 完了")
    return jsonify({
        "taskId": task_id,
        "status": "completed",
        "metadata": metadata
    })

@app.route('/health', methods=['GET'])
def health_check():
    """簡単なヘルスチェック用エンドポイント"""
    return jsonify({"status": "ok"})


#----------------------------------------------
# 7. A2A連携機能（エージェント探索・通信）
#----------------------------------------------
def discover_agents(skill=None, capability=None, content_type=None):
    """利用可能なエージェントを発見する（Agent Discovery）
    
    Args:
        skill: 特定のスキル名で検索（例: "recipe_extraction"）
        capability: より一般的な能力の説明（例: "extract recipe from text"）
        content_type: 処理するコンテンツの種類（例: "recipe", "meeting_notes"）
        
    Returns:
        発見されたエージェントのリスト
    """
    # Docker環境検出
    is_docker = os.environ.get('DOCKER_ENV', '').lower() == 'true' or os.path.exists('/.dockerenv')
    
    if is_docker:
        # Docker環境のサービス名を使用（docker-compose.ymlに合わせる）
        known_agents = [
            "http://recipe-extractor:5001",  # レシピ抽出エージェント
            "http://notion-agent:5002"       # Notion連携エージェント
        ]
    else:
        # 開発環境 (localhost) で実行する場合
        known_agents = [
            "http://localhost:5001",  # レシピ抽出エージェント
            "http://localhost:5002"   # Notion連携エージェント
        ]
    
    discovered_agents = []
    
    for agent_base_url in known_agents:
        try:
            # Agent Cardを取得
            agent_card_url = f"{agent_base_url}/.well-known/agent.json"
            logger.info(f"🔍 エージェント探索: {agent_card_url} に接続を試みています...")
            response = requests.get(agent_card_url, timeout=5)
            
            if response.status_code == 200:
                agent_card = response.json()
                agent_info = {
                    "url": agent_card.get("url", agent_base_url),
                    "name": agent_card.get("name", "Unknown Agent"),
                    "skills": [s.get("name") for s in agent_card.get("skills", [])],
                    "agent_card": agent_card
                }
                
                # スキル名指定の場合: 正確なスキル名でフィルタリング
                if skill and not any(skill.lower() in s.lower() for s in agent_info["skills"]):
                    if not query_agent_skill(agent_base_url, skill):
                        continue  # このエージェントはスキルを持っていないのでスキップ
                
                # 能力ベースの場合: より柔軟な能力のマッチング（将来のQuerySkill拡張）
                if capability and not query_agent_capability(agent_base_url, capability):
                    continue  # このエージェントは要求された能力を持っていない
                
                # コンテンツタイプの場合: コンテンツタイプに対応できるかを確認
                if content_type and not can_handle_content(agent_base_url, content_type):
                    continue  # このエージェントはこのタイプのコンテンツを扱えない
                
                # すべての条件を満たしたエージェントを追加
                discovered_agents.append(agent_info)
                logger.info(f"🔍 エージェント発見: {agent_info['name']} at {agent_base_url}")
                
        except Exception as e:
            logger.error(f"⚠️ エージェント探索エラー ({agent_base_url}): {e}")
    
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
        capability_description: 能力の説明（例: "extract recipe from text"）
    
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
        content_type: コンテンツのタイプ（例: "recipe", "meeting_notes"）
    
    Returns:
        bool: 処理可能ならTrue
    """
    # 現段階ではQuerySkillを使用
    return query_agent_capability(agent_url, f"process {content_type} content")

def analyze_content_type(text):
    """テキストの内容からコンテンツタイプを推定する
    
    Args:
        text: 分析するテキスト
    
    Returns:
        string: 推定されたコンテンツタイプ
    """
    # 簡易実装：キーワードベースの判定
    # 実際の実装ではより洗練された分析が必要
    lower_text = text.lower()
    
    # レシピ関連のキーワード
    recipe_keywords = ["材料", "レシピ", "調理", "グラム", "小さじ", "大さじ", "recipe", "ingredients", "cooking", "instructions"]
    if any(keyword in lower_text for keyword in recipe_keywords):
        return "recipe"
    
    # 他の種類のコンテンツも必要に応じて追加
    # ...
    
    # デフォルト
    return "general_text"

def send_to_next_agent(task_id, youtube_url, final_text, metadata=None):
    """次のエージェントにタスクを送信する - A2A自律連携実装
    
    コンテンツの分析に基づいて適切なエージェントを動的に選択し、
    処理を次のエージェントに委託します。
    """
    # 1. コンテンツタイプを分析
    content_type = analyze_content_type(final_text)
    logger.info(f"[{task_id}] 📝 コンテンツ分析結果: '{content_type}'タイプのコンテンツと判断されました")
    
    # 2. コンテンツタイプに対応できるエージェントを探す（A2A発見プロセス）
    if content_type == "recipe":
        # レシピコンテンツと判断された場合の処理
        logger.info(f"[{task_id}] 🔍 レシピ処理が可能なエージェントを探しています...")
        # まず「レシピ抽出」能力を持つエージェントを探す
        discovered_agents = discover_agents(capability="extract recipe from text")
        
        # 見つからなければより一般的なスキル名で探す
        if not discovered_agents:
            logger.info(f"[{task_id}] 🔍 一般的なレシピ関連スキルを持つエージェントを探しています...")
            discovered_agents = discover_agents(skill="recipe")
    else:
        # その他のコンテンツタイプの場合
        logger.info(f"[{task_id}] 🔍 '{content_type}'の処理が可能なエージェントを探しています...")
        discovered_agents = discover_agents(content_type=content_type)
    
    # 3. 適切なエージェントが見つからなかった場合のフォールバック
    if not discovered_agents:
        logger.info(f"[{task_id}] ⚠️ 適切なエージェントが見つかりませんでした。すべてのエージェントを確認します。")
        discovered_agents = discover_agents()  # スキル指定なしで全エージェント取得
    
    # エージェントが見つからない場合
    if not discovered_agents:
        logger.error(f"[{task_id}] ❌ タスクを転送できるエージェントが見つかりませんでした")
        return False
    
    # 4. 最適なエージェントを選択（ここでは単純に最初のエージェントを使用）
    # 実際の実装ではランキングやスコアリングなどより洗練された選択方法を使用すべき
    selected_agent = discovered_agents[0]
    agent_url = selected_agent["url"]
    tasks_endpoint = f"{agent_url}/tasks/send"
    
    logger.info(f"[{task_id}] 🔄 タスクの転送先として '{selected_agent['name']}' が選択されました")
    
    # メタデータがなければ空のオブジェクトを作成
    if metadata is None:
        metadata = {}
    
    # 5. タスクデータの構築 - A2Aプロトコルに準拠
    task_data = {
        "taskId": task_id,  # 同じタスクIDを維持
        "metadata": {
            "flow_step": "recipe",  # 次のステップを指定
            "flow_completed": False,  # フローはまだ完了していない
            "youtube_url": youtube_url,
            "channel_name": metadata.get("channel_name", "不明"),
            "thumbnail_url": metadata.get("thumbnail_url", ""),
            "video_title": metadata.get("video_title", ""),
            "content_type": content_type,
            "source_agent": "youtube_agent"
        },
        "message": {
            "parts": [
                # 明示的なアーティファクトタイプを設定
                {
                    "mimeType": "text/plain",
                    "text": final_text
                },
                # YouTubeのURLを明示的に渡す（text/uri-list形式）
                {
                    "mimeType": "text/uri-list",
                    "text": youtube_url
                },
                # メタデータも保持するためにJSONフォーマットも含める
                {
                    "mimeType": "application/json",
                    "data": {
                        "youtube_url": youtube_url,
                        "channel_name": metadata.get("channel_name", "不明"),
                        "thumbnail_url": metadata.get("thumbnail_url", ""),
                        "content_type": content_type
                    }
                }
            ]
        }
    }
    
    # 6. 次のエージェントにタスクを転送
    try:
        logger.info(f"[{task_id}] 🔄 '{selected_agent['name']}'にタスクを転送中...")
        response = requests.post(tasks_endpoint, json=task_data, timeout=300)

        # 応答の検証
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
# 8. YouTube処理機能 (字幕取得・音声文字起こし)
#----------------------------------------------
def download_subtitles(youtube_url, preferred_langs=None):
    """
    YouTube動画の字幕を youtube-transcript-api で取得しテキストを返す関数

    Args:
        youtube_url: YouTube動画のURL
        preferred_langs: 字幕の優先言語（リスト、例: ["ja", "en"]）

    Returns:
        字幕テキスト（取得できなかった場合は空文字列）
    """
    if not preferred_langs:
        preferred_langs = SUBTITLE_LANG.copy()

    # 動画IDを抽出
    match = re.search(r'(?:v=|youtu\.be/)([^&\n?#]+)', youtube_url)
    if not match:
        logger.error(f"無効なYouTube URL: {youtube_url}")
        return ""

    video_id = match.group(1)
    logger.info(f"字幕取得を開始 (video_id: {video_id}), 優先言語: {preferred_langs}")

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=preferred_langs)
        subtitle_text = "\n".join(snippet.text for snippet in fetched)
        logger.info(f"字幕取得完了 ({len(subtitle_text)}文字)")
        return subtitle_text

    except TranscriptsDisabled:
        logger.info("この動画では字幕が無効になっています")
        return ""
    except VideoUnavailable:
        logger.error("動画が利用できません")
        return ""
    except NoTranscriptFound:
        logger.info("指定言語の字幕が見つかりませんでした")
        return ""
    except Exception as e:
        logger.error(f"字幕ダウンロードエラー: {e}")
        return ""

#----------------------------------------------
# 9. メインアプリケーション実行
#----------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    logger.info(f"Starting Youtube Agent server on port {port}")
    serve(app, host='0.0.0.0', port=port) 