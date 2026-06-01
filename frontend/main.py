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
        youtube_task_id = task.get("youtube_task_id")
        response = requests.get(f"{YOUTUBE_AGENT_URL}/tasks/get?taskId={youtube_task_id}", timeout=5)

        if response.status_code == 200:
            youtube_task = response.json()
            status = youtube_task.get("status")
            metadata = youtube_task.get("metadata", {})

            if status == "completed":
                task["status"] = "completed"
                task["step"] = "completed"
                task["message"] = "レシピがNotionに登録されました"
                if metadata.get("notion_url"):
                    task["notion_url"] = metadata["notion_url"]

            elif status == "failed":
                task["status"] = "error"
                task["step"] = "error"
                error_info = youtube_task.get("error", {})
                task["message"] = error_info.get("message", "処理中にエラーが発生しました")

            # status == "working" の場合はそのまま processing を維持

        tasks[task_id] = task
        return task

    except Exception as e:
        logger.error(f"タスク状態の確認中にエラーが発生しました: {e}")
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
    serve(app, host=host, port=port) 