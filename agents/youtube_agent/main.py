# ファイル名: agents/youtube_agent/main.py
# 説明: YouTubeから動画の字幕および音声を抽出し、テキストに変換するエージェント

#----------------------------------------------
# 1. インポート
#----------------------------------------------
# 標準ライブラリ
import os
import json
import uuid
import time
import tempfile
from pathlib import Path

# サードパーティライブラリ
import requests
from flask import Flask, request, jsonify
import yt_dlp
from faster_whisper import WhisperModel
from waitress import serve

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

# Whisperモデル設定
MODEL_SIZE = "base"  # 使用するWhisperモデルのサイズ (tiny, base, small, medium, large-v2, large-v3)
DEVICE = "cpu"  # 使用するデバイス (cpu または cuda)
COMPUTE_TYPE = "int8"  # 量子化のタイプ (float16, int8_float16, int8)

# ダウンロード設定
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "youtube_audio_downloads"
USE_SUBTITLES = True  # YouTube字幕の取得を有効化
USE_TRANSCRIPTION = True  # 音声からの文字起こしを有効化
SUBTITLE_LANG = ["ja", "en"]  # 取得する字幕の優先言語 (先頭が最優先)

#----------------------------------------------
# 4. Flaskアプリケーション初期化
#----------------------------------------------
app = Flask(__name__)
app.logger.setLevel(logging.ERROR)

#----------------------------------------------
# 5. グローバル初期化処理
#----------------------------------------------
# アプリケーション起動時にモデルをロード
logger.info(f"faster-whisperモデルをロード中: {MODEL_SIZE}")
whisper_model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
logger.info("モデルのロードが完了しました。")

# ダウンロード用ディレクトリ作成
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

    transcription_text = ""
    subtitle_text = ""
    final_text = ""
    error_message = None
    task_status = "working" # 初期ステータス
    channel_name = None
    thumbnail_url = None

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
                               
                # サムネイルURLを取得
                thumbnail_url = (info_dict.get('thumbnail') or 
                                info_dict.get('thumbnails')[0]['url'] if info_dict.get('thumbnails') else None or
                                "")
                                
                logger.info(f"[{task_id}] チャンネル名: {channel_name}")
                logger.info(f"[{task_id}] サムネイルURL: {thumbnail_url[:50]}..." if thumbnail_url and len(thumbnail_url) > 50 else f"[{task_id}] サムネイルURL: {thumbnail_url}")
        except Exception as e:
            logger.warning(f"[{task_id}] 動画情報の取得でエラーが発生しました: {str(e)}")
            # エラーがあってもプロセスは続行（メタデータは任意）
            
        # --- 1. 字幕取得と音声文字起こしを並行処理 ---
        logger.info(f"[{task_id}] 処理を開始: {youtube_url}")
        
        # 字幕取得（設定で有効な場合）
        if USE_SUBTITLES:
            logger.info(f"[{task_id}] YouTube字幕取得を試みています...")
            subtitle_text = download_subtitles(youtube_url, SUBTITLE_LANG)
            if subtitle_text:
                logger.info(f"[{task_id}] YouTube字幕を取得しました（{len(subtitle_text)}文字）")
            else:
                logger.info(f"[{task_id}] YouTube字幕は利用できませんでした")
        
        # 音声文字起こし（設定で有効な場合）
        if USE_TRANSCRIPTION:
            if not subtitle_text or len(subtitle_text) < 100:  # 短すぎる字幕は役に立たない可能性が高い
                logger.info(f"[{task_id}] 音声文字起こしを開始します...")
                try:
                    transcription_text = transcribe_audio(youtube_url, task_id)
                    if transcription_text:
                        logger.info(f"[{task_id}] 音声文字起こしが完了しました（{len(transcription_text)}文字）")
                    else:
                        logger.info(f"[{task_id}] 音声文字起こしに失敗しました")
                except Exception as e:
                    # 文字起こしのエラーは深刻なので、エラーとして扱う
                    error_message = f"音声文字起こし処理でエラーが発生しました: {str(e)}"
                    logger.error(f"[{task_id}] {error_message}")
                    # 字幕があればそれを使い、なければエラー
                    if not subtitle_text:
                        task_status = "failed"
            else:
                logger.info(f"[{task_id}] 十分な字幕が得られたため、音声文字起こしをスキップします")
        
        # --- 2. 結果のマージと整形 ---
        if subtitle_text and transcription_text:
            # 両方の結果がある場合、セクションに分けて併記
            final_text = f"【字幕】\n{subtitle_text}\n\n【文字起こし】\n{transcription_text}"
            logger.info(f"[{task_id}] 字幕と文字起こし両方の結果を併記します（合計{len(final_text)}文字）")
        elif subtitle_text:
            # 字幕のみがある場合
            final_text = subtitle_text
            logger.info(f"[{task_id}] 字幕のみの結果を使用します（{len(final_text)}文字）")
        elif transcription_text:
            # 文字起こしのみがある場合
            final_text = transcription_text
            logger.info(f"[{task_id}] 文字起こしのみの結果を使用します（{len(final_text)}文字）")
        else:
            # どちらもない場合（エラー状態）
            error_message = "動画から字幕も音声も取得できませんでした"
            task_status = "failed"
            logger.error(f"[{task_id}] {error_message}")
        
        # --- 3. 結果の状態確認 ---
        if task_status != "failed" and final_text:
            task_status = "completed"
            logger.info(f"[{task_id}] タスク完了（処理時間: {time.time() - start_time:.2f}秒）")
            
            # その後、次のエージェントに転送
            metadata = {
                "channel_name": channel_name,
                "thumbnail_url": thumbnail_url
            }
            
            # A2A連携のために次のエージェントにタスクを転送
            send_result = send_to_next_agent(task_id, youtube_url, final_text, metadata)
            if not send_result:
                logger.warning(f"[{task_id}] 次のエージェントへの転送に失敗しましたが、タスク自体は完了しています")
        
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
    
    # 実際のタスク状態管理は実装されていないため、
    # ダミーのタスク情報を返す（実際の実装ではタスクの状態をデータベースや
    # メモリに保存してIDで検索できるようにします）
    
    # タスクの処理はA2A経由で完了しているため、通常はステータスを「完了」として返す
    dummy_task = {
        "taskId": task_id,
        "status": "completed",
        "metadata": {
            "flow_step": "completed",
            "flow_completed": True,
            "source_agent": "youtube_agent"
        },
        "artifacts": [
            {
                "type": "transcription",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "text": "トランスクリプションは完了済み"
                    }
                ]
            },
            {
                "type": "metadata",
                "parts": [
                    {
                        "mimeType": "application/json",
                        "data": {
                            "youtube_url": "https://www.youtube.com/watch?v=example",
                            "channel_name": "サンプルチャンネル",
                            "thumbnail_url": "https://example.com/thumbnail.jpg"
                        }
                    }
                ]
            }
        ]
    }
    
    logger.info(f"タスク状態の照会: {task_id} - 常に完了として応答")
    return jsonify(dummy_task)

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
        response = requests.post(tasks_endpoint, json=task_data, timeout=30)
        
        # 応答の検証
        if response.status_code == 200:
            result = response.json()
            logger.info(f"[{task_id}] ✅ '{selected_agent['name']}'がタスクを受理しました（ステータス: {result.get('status')}）")
            return True
        else:
            logger.warning(f"[{task_id}] ⚠️ '{selected_agent['name']}'からエラー応答: {response.status_code}")
            logger.warning(f"[{task_id}] ⚠️ エラー詳細: {response.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"[{task_id}] ⚠️ '{selected_agent['name']}'との通信エラー: {e}")
        return False

#----------------------------------------------
# 8. YouTube処理機能 (字幕取得・音声文字起こし)
#----------------------------------------------
def download_subtitles(youtube_url, preferred_langs=None):
    """
    YouTube動画の字幕をダウンロードし、テキスト形式で抽出する関数
    
    Args:
        youtube_url: YouTube動画のURL
        preferred_langs: 字幕の優先言語（リスト、例: ["ja", "en"]）
        
    Returns:
        字幕テキスト（取得できなかった場合は空文字列）
    """
    if not preferred_langs:
        preferred_langs = SUBTITLE_LANG.copy()  # デフォルトの言語リストを使用
    
    logger.info(f"字幕ダウンロードを開始: {youtube_url}")
    logger.info(f"優先言語: {preferred_langs}")
    
    # 一時ファイル名のベースを生成（ディレクトリのみ）
    temp_dir = tempfile.gettempdir()
    temp_filename_base = os.path.join(temp_dir, f"subtitle_{uuid.uuid4()}")
    
    try:
        # yt-dlpオプション
        ydl_opts = {
            'skip_download': True,  # 動画をダウンロードしない
            'writesubtitles': USE_SUBTITLES,  # フラグに連動: 字幕をダウンロード
            'writeautomaticsub': USE_SUBTITLES,  # フラグに連動: 自動生成字幕もダウンロード
            'subtitleslangs': preferred_langs,  # 優先言語
            'subtitlesformat': 'srt',  # 字幕形式
            'outtmpl': f'{temp_filename_base}.%(ext)s',  # 出力ファイル
            'quiet': True,  # 出力抑制
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=False)
            
            # 字幕情報の確認
            subtitle_info = {}
            if 'subtitles' in info_dict and info_dict['subtitles']:
                subtitle_info = info_dict['subtitles']
                logger.info(f"利用可能な手動字幕: {list(subtitle_info.keys())}")
            
            auto_subtitle_info = {}
            if 'automatic_captions' in info_dict and info_dict['automatic_captions']:
                auto_subtitle_info = info_dict['automatic_captions']
                logger.info(f"利用可能な自動生成字幕: {list(auto_subtitle_info.keys())}")
            
            # 言語優先順で字幕を取得
            used_lang = None
            for lang in preferred_langs:
                # まず手動追加の字幕を確認
                if lang in subtitle_info:
                    used_lang = lang
                    logger.info(f"手動字幕を使用: {lang}")
                    break
                # なければ自動生成字幕を確認
                elif lang in auto_subtitle_info:
                    used_lang = lang
                    logger.info(f"自動生成字幕を使用: {lang}")
                    break
            
            # どの言語も利用可能でない場合
            if not used_lang:
                logger.info("利用可能な字幕が見つかりませんでした")
                return ""
                
            # 字幕をダウンロード
            ydl.download([youtube_url])
            
            # ダウンロードされたファイルを探す
            subtitle_file = None
            for ext in ['vtt', 'srt']:
                # 手動字幕を探す
                manual_path = Path(f"{temp_filename_base}.{used_lang}.{ext}")
                if manual_path.exists():
                    subtitle_file = manual_path
                    break
                    
                # 自動生成字幕を探す
                auto_path = Path(f"{temp_filename_base}.{used_lang}.auto.{ext}")
                if auto_path.exists():
                    subtitle_file = auto_path
                    break
            
            if subtitle_file and subtitle_file.exists():
                logger.info(f"字幕ファイルを見つけました: {subtitle_file}")
                
                # 字幕ファイルを読み込み、整形
                with open(subtitle_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # SRTまたはVTTからテキストのみを抽出
                import re
                if subtitle_file.suffix == '.srt':
                    # SRTからテキスト抽出 (番号、時間表記を削除)
                    lines = []
                    for line in content.split('\n'):
                        # 番号行や時間表記行をスキップ
                        if re.match(r'^\d+$', line.strip()) or re.match(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}', line.strip()):
                            continue
                        if line.strip():
                            lines.append(line.strip())
                    subtitle_text = '\n'.join(lines)
                else:
                    # VTTからテキスト抽出
                    lines = []
                    for line in content.split('\n'):
                        # 時間表記行や空行をスキップ
                        if re.match(r'WEBVTT', line.strip()) or re.match(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', line.strip()):
                            continue
                        if line.strip() and not line.strip().startswith('NOTE') and not line.strip().startswith('Kind:'):
                            lines.append(line.strip())
                    subtitle_text = '\n'.join(lines)
                
                # 不要なファイルの削除
                try:
                    os.remove(subtitle_file)
                    logger.info(f"字幕ファイルを削除しました: {subtitle_file}")
                except OSError as e:
                    logger.error(f"字幕ファイル削除エラー: {e}")
                    
                return subtitle_text
            else:
                logger.info("字幕ファイルが見つかりませんでした")
                return ""
                
    except Exception as e:
        logger.error(f"字幕ダウンロードエラー: {e}")
        return ""

def transcribe_audio(youtube_url, task_id=None):
    """
    YouTube動画の音声をダウンロードし、文字起こしを行う関数
    
    Args:
        youtube_url: YouTube動画のURL
        task_id: タスクID（ログ出力用）
        
    Returns:
        (transcription_text, error_message, audio_path)のタプル
        - transcription_text: 文字起こしされたテキスト（エラー時は空文字列）
        - error_message: エラーメッセージ（成功時はNone）
        - audio_path: ダウンロードした音声ファイルパス（クリーンアップ用、エラー時はNone）
    """
    if not task_id:
        task_id = str(uuid.uuid4())
        
    logger.info(f"[{task_id}] 音声文字起こしを開始します...")
    audio_path = None
    
    try:
        # 一時ファイル名を設定
        temp_audio_file = DOWNLOAD_DIR / f"audio_{task_id}.wav"
        audio_path = temp_audio_file
        
        # yt-dlpオプション
        ydl_opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,  # 音声の抽出
            'noplaylist': True,  # プレイリストをダウンロードしない
            'outtmpl': str(temp_audio_file).replace('.wav', ''),  # 出力パス（拡張子はyt-dlpが自動追加）
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',  # WAV形式に変換（whisperのデコードに最適）
                'preferredquality': '192',  # 音質
            }],
            'quiet': True  # 出力抑制
        }
        
        # ダウンロード実行
        logger.info(f"[{task_id}] YouTube動画の音声をダウンロード中...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
            
        # ファイルパスの確認（yt-dlpによって拡張子が付加されている可能性）
        if audio_path.with_suffix('.wav').exists():
            audio_path = audio_path.with_suffix('.wav')
        elif audio_path.with_suffix('.m4a').exists():
            audio_path = audio_path.with_suffix('.m4a')
        elif audio_path.with_suffix('.mp3').exists():
            audio_path = audio_path.with_suffix('.mp3')
        else:
            # 他の可能性のある拡張子を確認
            for ext in ['.aac', '.flac', '.opus', '.webm']:
                if audio_path.with_suffix(ext).exists():
                    audio_path = audio_path.with_suffix(ext)
                    break
        
        if not audio_path.exists():
            logger.error(f"[{task_id}] ダウンロードした音声ファイルが見つかりません")
            return "", "Downloaded audio file not found", None
            
        logger.info(f"[{task_id}] 音声ファイル: {audio_path}")
        logger.info(f"[{task_id}] Whisperモデルによる文字起こしを開始...")
        
        # Whisperモデルで文字起こし
        segments, info = whisper_model.transcribe(str(audio_path), beam_size=5)
        
        # 結果を結合して返す
        transcription_lines = []
        for segment in segments:
            transcription_lines.append(segment.text)
        
        transcription_text = "\n".join(transcription_lines)
        logger.info(f"[{task_id}] 文字起こし完了（長さ: {len(transcription_text)} 文字）")
        
        # 言語の確認（ログ出力用）
        detected_language = info.language
        language_probability = info.language_probability
        logger.info(f"[{task_id}] 検出された言語: {detected_language}, 確率: {language_probability:.4f}")
        
        return transcription_text, None, audio_path
        
    except Exception as e:
        logger.error(f"[{task_id}] 文字起こし処理でエラーが発生しました: {e}")
        
        # 詳細なエラーメッセージ
        import traceback
        error_details = traceback.format_exc()
        logger.debug(f"[{task_id}] エラー詳細:\n{error_details}")
        
        return "", f"Transcription error: {e}", audio_path

#----------------------------------------------
# 9. メインアプリケーション実行
#----------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    logger.info(f"Starting Youtube Agent server on port {port}")
    serve(app, host='0.0.0.0', port=port) 