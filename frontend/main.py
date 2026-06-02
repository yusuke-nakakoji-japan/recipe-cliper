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
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

# サードパーティライブラリ
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
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
# 認証設定
#----------------------------------------------
AUTH_USERNAME = os.environ.get('AUTH_USERNAME', '')
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD', '')
MAX_FAILED_ATTEMPTS = 5      # 最大失敗回数
LOCKOUT_DURATION    = 15 * 60  # ロックアウト時間（秒）

# IPごとの失敗記録: {ip: {"count": int, "lockout_until": float}}
_failed_attempts: dict = {}

def _get_client_ip() -> str:
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()

def _is_locked(ip: str) -> bool:
    entry = _failed_attempts.get(ip)
    if not entry:
        return False
    if entry["lockout_until"] > time.time():
        return True
    # ロックアウトが「設定済みかつ期限切れ」の場合のみ記録をクリアする。
    # （まだロック前で失敗カウント蓄積中=lockout_until が 0 のときは消さない）
    if entry["lockout_until"] > 0:
        _failed_attempts.pop(ip, None)
    return False

def _record_failure(ip: str) -> None:
    entry = _failed_attempts.setdefault(ip, {"count": 0, "lockout_until": 0.0})
    entry["count"] += 1
    if entry["count"] >= MAX_FAILED_ATTEMPTS:
        entry["lockout_until"] = time.time() + LOCKOUT_DURATION
        logger.warning(f"[Auth] IP {ip} がログイン {MAX_FAILED_ATTEMPTS} 回失敗: {LOCKOUT_DURATION // 60}分ロックアウト")

def _clear_failure(ip: str) -> None:
    _failed_attempts.pop(ip, None)

def require_auth(f):
    """セッションベースの認証デコレータ（未認証はログイン画面へ誘導）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('authenticated'):
            return f(*args, **kwargs)

        # 未認証時: APIエンドポイントはJSONで401を返し、フロントJSが扱えるようにする
        if request.path.startswith('/submit') or request.path.startswith('/status'):
            return jsonify({
                "status": "error",
                "message": "セッションが切れました。お手数ですが再度ログインしてください。"
            }), 401

        # 通常のページリクエストはログイン画面へリダイレクト
        return redirect(url_for('login'))
    return decorated

#----------------------------------------------
# 4. Flaskアプリケーション初期化
#----------------------------------------------
app = Flask(__name__)

# セッション（署名付きCookie）設定
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    # HTTPS(Tailscale Funnel等)経由のアクセスを前提に Secure を付与。
    # ローカルのhttpで検証したい場合は環境変数 SESSION_COOKIE_SECURE=false で無効化可能。
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true',
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
if not os.environ.get('SECRET_KEY'):
    logger.warning(
        "SECRET_KEY が未設定のため一時キーを使用します。"
        "再起動でログインセッションが無効化されるため、.env に SECRET_KEY を設定することを推奨します。"
    )

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
@app.route('/login', methods=['GET', 'POST'])
def login():
    """ログイン画面の表示と認証処理（HTMLフォーム＋セッション）"""
    # 既にログイン済みならトップへ
    if session.get('authenticated'):
        return redirect(url_for('index'))

    ip = _get_client_ip()

    if request.method == 'POST':
        # ロックアウト中はログイン処理を行わない
        if _is_locked(ip):
            remaining = int(_failed_attempts[ip]["lockout_until"] - time.time())
            return render_template(
                'login.html',
                error=f"アクセスがロックされています。あと {remaining} 秒後に再試行してください。"
            ), 403

        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if AUTH_USERNAME and username == AUTH_USERNAME and password == AUTH_PASSWORD:
            _clear_failure(ip)
            session['authenticated'] = True
            session.permanent = True
            logger.info(f"[Auth] ログイン成功 (IP: {ip})")
            return redirect(url_for('index'))

        # 認証失敗
        _record_failure(ip)
        logger.warning(f"[Auth] ログイン失敗 (IP: {ip})")
        if _is_locked(ip):
            return render_template(
                'login.html',
                error=f"ログインに {MAX_FAILED_ATTEMPTS} 回失敗しました。{LOCKOUT_DURATION // 60} 分間アクセスがロックされます。"
            ), 403
        return render_template(
            'login.html',
            error="ユーザー名またはパスワードが正しくありません。"
        ), 401

    # GET: ログインフォームを表示
    return render_template('login.html')

@app.route('/logout')
def logout():
    """ログアウト（セッション破棄）"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@require_auth
def index():
    """トップページを表示"""
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
@require_auth
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
@require_auth
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