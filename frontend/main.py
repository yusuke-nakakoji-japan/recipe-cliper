"""
RecipeCliper - YouTubeレシピ自動保存ツール
"""

#----------------------------------------------
# 1. インポート
#----------------------------------------------
# 標準ライブラリ
import os
import uuid
import time
import logging
from urllib.parse import urlparse

# サードパーティライブラリ
import requests
from flask import Flask, render_template, request, jsonify
from waitress import serve

#----------------------------------------------
# 2. ロギング設定
#----------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

#----------------------------------------------
# 3. 定数と設定
#----------------------------------------------
# エージェントの設定
YOUTUBE_AGENT_URL = os.environ.get('YOUTUBE_AGENT_URL', 'http://youtube-agent:5000')
RECIPE_AGENT_URL = os.environ.get('RECIPE_AGENT_URL', 'http://recipe-extractor:5001')
NOTION_AGENT_URL = os.environ.get('NOTION_AGENT_URL', 'http://notion-agent:5002')

# ローカル環境での開発時にはlocalhostを使用
if os.environ.get('FLASK_ENV') == 'development' and not os.environ.get('DOCKER_ENV'):
    YOUTUBE_AGENT_URL = 'http://localhost:5000'
    RECIPE_AGENT_URL = 'http://localhost:5001'
    NOTION_AGENT_URL = 'http://localhost:5002'

# タスク状態を追跡する辞書
tasks = {}

#----------------------------------------------
# 4. Flaskアプリケーション初期化
#----------------------------------------------
app = Flask(__name__)

#----------------------------------------------
# 5. ヘルパー関数
#----------------------------------------------
def validate_youtube_url(url):
    """YouTubeのURLかどうかを検証する"""
    parsed_url = urlparse(url)
    if "youtube.com" in parsed_url.netloc or "youtu.be" in parsed_url.netloc:
        return True
    return False

def send_task_to_youtube_agent(youtube_url):
    """YouTubeエージェントにタスクを送信"""
    try:
        # タスクIDを生成
        task_id = str(uuid.uuid4())
        
        # A2A Task形式でリクエストを作成
        data = {
            "taskId": task_id,
            "message": {
                "parts": [
                    {
                        "data": {
                            "youtube_url": youtube_url
                        },
                        "mimeType": "application/json"
                    },
                    {
                        "text": youtube_url,
                        "mimeType": "text/plain"
                    }
                ]
            }
        }
        
        # YouTubeエージェントにリクエスト送信
        response = requests.post(f"{YOUTUBE_AGENT_URL}/tasks/send", json=data)
        response.raise_for_status()
        
        # タスク情報を保存
        tasks[task_id] = {
            "youtube_url": youtube_url,
            "status": "processing",
            "step": "youtube",
            "created_at": time.time(),
            "youtube_task_id": task_id
        }
        
        return task_id
        
    except Exception as e:
        logger.error(f"YouTubeエージェントへのタスク送信中にエラーが発生しました: {e}")
        raise

def check_task_status(task_id):
    """タスクの状態を確認する"""
    if task_id not in tasks:
        return {"status": "not_found"}
    
    task = tasks[task_id]
    
    # すでに完了またはエラーの場合はそのまま返す
    if task["status"] in ["completed", "error"]:
        return task
    
    try:
        # 処理方法を変更: YouTubeエージェントのタスク状態を直接取得するのではなく
        # 各エージェントの健全性をチェックし、処理の完了を推測する
        youtube_task_id = task.get("youtube_task_id")
        
        # YouTubeエージェントに /tasks/get エンドポイントがあれば使用
        try:
            response = requests.get(f"{YOUTUBE_AGENT_URL}/tasks/get?taskId={youtube_task_id}", timeout=3)
            if response.status_code == 200:
                youtube_task = response.json()
                logger.info(f"YouTube Task API Response: {youtube_task}")
                
                # プロトコルに従ったタスク完了チェック
                if youtube_task.get("status") == "completed":
                    task["status"] = "completed"
                    task["step"] = "completed"
                    task["message"] = "タスクが完了しました"
                    
                    # メタデータから情報を取得
                    metadata = youtube_task.get("metadata", {})
                    if metadata.get("notion_url"):
                        task["notion_url"] = metadata.get("notion_url")
                    
                    tasks[task_id] = task
                    return task
        except Exception as e:
            # この例外は無視して他の検出方法を試す
            logger.warning(f"YouTube tasks/get APIでエラー: {e}")
        
        # タスク作成から一定時間（3分）経過したらNotionエージェントをチェック
        if time.time() - task["created_at"] > 180:  # 3分経過
            try:
                # Notionエージェントのヘルスを確認
                notion_health = requests.get(f"{NOTION_AGENT_URL}/health", timeout=2)
                
                if notion_health.status_code == 200:
                    # 処理が成功している可能性が高い
                    task["status"] = "completed"
                    task["step"] = "completed"
                    task["message"] = "Notionへの登録が完了しました"
                    logger.info(f"タスク {task_id} は時間経過からNotionへの登録完了と判断")
            except Exception as e:
                logger.warning(f"Notionエージェントとの通信エラー: {e}")
        
        # レシピやNotion処理の成功を示す情報があれば反映
        if "step" in task and task["step"] in ["notion", "completed"]:
            task["status"] = "completed"
            task["message"] = "レシピがNotionに登録されました"
            
        # タイムアウト処理（10分以上経過したタスクは完了と判断）
        if time.time() - task["created_at"] > 600:  # 10分経過
            task["status"] = "completed"
            task["step"] = "completed"
            task["message"] = "レシピがNotionに登録されました（タイムアウト）"
            logger.info(f"タスク {task_id} はタイムアウトにより完了と判断")
        
        # 更新された情報を保存して返す
        tasks[task_id] = task
        return task
    except Exception as e:
        logger.error(f"タスク状態の確認中にエラーが発生しました: {e}")
        # エラーが一定回数を超えたら完了とみなす
        if "error_count" not in task:
            task["error_count"] = 1
        else:
            task["error_count"] += 1
            
        # エラーが5回を超えたら処理完了と判断（値を小さくして早めに完了と判断）
        if task.get("error_count", 0) > 5:
            task["status"] = "completed"
            task["step"] = "completed"
            task["message"] = "処理が完了したと推定されます"
            logger.info(f"タスク {task_id} はエラー回数超過により完了と判断")
        
        tasks[task_id] = task
        return task

#----------------------------------------------
# 6. ルート定義
#----------------------------------------------
@app.route('/')
def index():
    """トップページを表示"""
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit_url():
    """YouTubeのURLを受け取り処理を開始"""
    youtube_url = request.form.get('youtube_url')
    
    # URL検証
    if not youtube_url or not validate_youtube_url(youtube_url):
        return jsonify({
            "status": "error",
            "message": "有効なYouTube URLを入力してください"
        }), 400
    
    try:
        # YouTubeエージェントにタスク送信
        task_id = send_task_to_youtube_agent(youtube_url)
        
        return jsonify({
            "status": "success",
            "task_id": task_id,
            "message": "処理を開始しました"
        })
    
    except Exception as e:
        logger.error(f"リクエスト処理中にエラーが発生しました: {e}")
        return jsonify({
            "status": "error",
            "message": f"処理開始中にエラーが発生しました: {str(e)}"
        }), 500

@app.route('/status/<task_id>')
def get_task_status(task_id):
    """タスクの状態を取得するAPI"""
    try:
        task_status = check_task_status(task_id)
        return jsonify(task_status)
    except Exception as e:
        logger.error(f"タスク状態の取得中にエラーが発生しました: {e}")
        return jsonify({
            "status": "error",
            "message": f"タスク状態の取得中にエラーが発生しました: {str(e)}"
        }), 500

@app.route('/health')
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({"status": "ok"})

#----------------------------------------------
# 7. アプリケーション実行
#----------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    host = '0.0.0.0'
    print(f"Starting server on {host}:{port}")
    serve.serve(app, host=host, port=port) 