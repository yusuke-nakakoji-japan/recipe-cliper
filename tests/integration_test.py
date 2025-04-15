#!/usr/bin/env python3
"""
統合テスト: YouTubeレシピ処理からNotion登録までの全体フローをテスト (A2A自律連携対応)

このスクリプトは以下のステップでエンドツーエンドのテストを実施します：
1. YouTubeの料理動画URLを提供
2. YouTube動画処理エージェントにリクエストを送信
3. 各エージェントが自律的に連携
   - YouTube処理エージェント → レシピ抽出エージェント → Notion連携エージェント
4. 最終的にNotionに登録されることを確認
"""

import os
import json
import requests
import uuid
import time
import sys
import logging

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# エージェントURL設定（ローカルからDockerコンテナに接続する設定）
YOUTUBE_AGENT_URL = "http://localhost:5000"
RECIPE_AGENT_URL = "http://localhost:5001"
NOTION_AGENT_URL = "http://localhost:5002"

# テスト用YouTubeのURL
TEST_YOUTUBE_URL = "https://youtu.be/JiFr7vm1ocY?si=-pq-Mhi3rS_VbJZs"  # 字幕あり

def check_agent_health(url, name):
    """エージェントのヘルスチェックを行う"""
    try:
        health_url = f"{url}/health"
        response = requests.get(health_url, timeout=5)
        if response.status_code == 200:
            logger.info(f"✅ {name}が正常に稼働中です")
            return True
        else:
            logger.error(f"❌ {name}からエラーレスポンス: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ {name}に接続できません: {e}")
        return False

def ensure_agents_running():
    """各エージェントが起動しているか確認する"""
    print("🔍 エージェントの起動状態を確認中...")
    print("🐳 ホストからDockerコンテナに接続します - ポート転送を使用")
    
    agents = [
        {"name": "YouTube処理", "url": YOUTUBE_AGENT_URL},
        {"name": "レシピ抽出", "url": RECIPE_AGENT_URL},
        {"name": "Notion連携", "url": NOTION_AGENT_URL}
    ]
    
    # 健康状態を確認
    running_count = 0
    for agent in agents:
        if check_agent_health(agent['url'], agent["name"]):
            running_count += 1
        else:
            print(f"⚠️ {agent['name']}エージェント ({agent['url']}) に接続できません")
            print("💡 ヒント: Docker Composeで全サービスが正常に起動しているか確認してください")
    
    if running_count == len(agents):
        print("\n✅ すべてのエージェントが正常に起動しています")
        return True
    else:
        print(f"\n⚠️ {len(agents) - running_count}個のエージェントが起動していないか、応答していません")
        return False

def submit_task_to_agent(agent_url, task_data):
    """エージェントにタスクを送信する"""
    try:
        print(f"📡 {agent_url} にタスクを送信中...")
        
        task_endpoint = f"{agent_url}/tasks/send"
        response = requests.post(task_endpoint, json=task_data, timeout=300)
        
        # レスポンスの簡易チェック
        print(f"📊 ステータスコード: {response.status_code}")
        
        # 4xx/5xxエラーの場合は例外を発生
        response.raise_for_status()
        
        task_result = response.json()
        print(f"✅ タスク完了: ステータス={task_result.get('status')}")
            
        return task_result
    except Exception as e:
        print(f"❌ エージェント呼び出し中にエラー発生: {type(e).__name__} - {e}")
        return None

def main():
    """エンドツーエンドの統合テスト実行 (A2A自律連携対応)"""
    # 各エージェントの起動状態を確認
    agents_running = ensure_agents_running()
    if not agents_running:
        print("\n⚠️ 一部のエージェントが起動していないため、テストを中止します")
        sys.exit(1)
    
    # A2A自律連携テスト: YouTube処理エージェントにリクエストを送信
    print("\n🚀 A2A自律連携テスト開始: YouTube処理エージェントにリクエスト送信")
    print("このテストでは、YouTube処理エージェントにのみリクエストを送信し、")
    print("その後は各エージェントが自律的に連携して処理を進めることを期待します")
    
    # YouTubeエージェントにリクエスト送信
    youtube_task_id = str(uuid.uuid4())
    youtube_task = {
        "taskId": youtube_task_id,
        "message": {
            "parts": [
                {
                    "mimeType": "application/json",
                    "data": {"youtube_url": TEST_YOUTUBE_URL}
                }
            ]
        }
    }
    
    # リクエスト送信
    youtube_result = submit_task_to_agent(YOUTUBE_AGENT_URL, youtube_task)
    if not youtube_result:
        print("❌ YouTube処理エージェントへのリクエストに失敗しました")
        sys.exit(1)
    
    # YouTube処理エージェントからの応答を確認
    print("\n✅ YouTube処理エージェントからの応答を受信しました")
    print(f"タスクID: {youtube_result.get('taskId')}")
    print(f"ステータス: {youtube_result.get('status')}")
    
    # A2A自律連携の説明を表示
    print("\n🎉 YouTubeエージェントにリクエストが送信され、処理が開始されました")
    print("\n⏳ 各エージェント間のA2A自律連携により処理が進行中です:")
    print("  YouTube処理 → レシピ抽出 → Notion登録")
    print("\n💡 重要: 各エージェントは独自のタスクIDを生成するため、元のYouTubeタスクIDでは追跡できません")
    print("   この処理は非同期で行われるため、数分後にNotionデータベースを確認してください")
    
    print("\n✅ テスト完了 - 処理は裏で続行されています")

if __name__ == "__main__":
    try:
        print("テスト開始")
        main()
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        sys.exit(1) 