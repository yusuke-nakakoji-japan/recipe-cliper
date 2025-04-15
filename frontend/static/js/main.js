/**
 * YouTubeレシピNotion自動登録ツール フロントエンドJS
 */

// DOM要素
const urlForm = document.getElementById('url-form');
const youtubeUrlInput = document.getElementById('youtube_url');
const submitBtn = document.getElementById('submit-btn');
const statusContainer = document.getElementById('status-container');
const statusMessage = document.getElementById('status-message');
const resultContainer = document.getElementById('result-container');
const resultSuccess = document.getElementById('result-success');
const resultError = document.getElementById('result-error');
const errorMessage = document.getElementById('error-message');
const retryBtn = document.getElementById('retry-btn');
const newClipBtn = document.getElementById('new-clip-btn');

// 変数
let currentTaskId = null;
let pollingInterval = null;

// ポーリング間隔（ミリ秒）
const POLLING_INTERVAL = 3000;

/**
 * フォーム送信イベントハンドラ
 */
urlForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const youtubeUrl = youtubeUrlInput.value.trim();
    
    if (!youtubeUrl) {
        showError('YouTube URLを入力してください');
        return;
    }
    
    // UI初期化
    resetUI();
    showProcessing();
    
    try {
        // フォームデータ作成
        const formData = new FormData();
        formData.append('youtube_url', youtubeUrl);
        
        // 送信リクエスト
        const response = await fetch('/submit', {
            method: 'POST',
            body: formData
        });
        
        // レスポンス処理
        const data = await response.json();
        
        if (response.ok && data.status === 'success') {
            // タスクID取得とポーリング開始
            currentTaskId = data.task_id;
            startPolling(currentTaskId);
        } else {
            // エラー表示
            showError(data.message || 'リクエスト処理中にエラーが発生しました');
        }
    } catch (error) {
        console.error('Error:', error);
        showError('通信エラーが発生しました');
    }
});

/**
 * 再試行ボタンのイベントハンドラ
 */
retryBtn.addEventListener('click', function() {
    resetUI();
    urlForm.reset();
    submitBtn.disabled = false;
});

/**
 * 別の料理動画をクリップするボタンのイベントハンドラ
 */
newClipBtn.addEventListener('click', function() {
    resetUI();
    urlForm.reset();
    submitBtn.disabled = false;
});

/**
 * タスク状態のポーリングを開始
 * @param {string} taskId タスクID
 */
function startPolling(taskId) {
    // 既存のポーリングをクリア
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
    
    // 新しいポーリングを設定
    pollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/status/${taskId}`);
            const data = await response.json();
            
            // ステータスに応じて表示を更新
            updateStatus(data);
            
            // 完了またはエラーの場合はポーリング停止
            if (data.status === 'completed' || data.status === 'error' || data.status === 'not_found') {
                clearInterval(pollingInterval);
                
                if (data.status === 'completed') {
                    showComplete(data);
                } else if (data.status === 'error') {
                    showError(data.message || 'タスク処理中にエラーが発生しました');
                } else if (data.status === 'not_found') {
                    showError('タスクが見つかりませんでした');
                }
            }
        } catch (error) {
            console.error('Polling error:', error);
            // エラー時もポーリングは継続（接続の一時的な問題の可能性）
        }
    }, POLLING_INTERVAL);
}

/**
 * 処理中の表示を行う
 */
function showProcessing() {
    statusContainer.style.display = 'block';
    resultContainer.style.display = 'none';
    submitBtn.disabled = true;
    youtubeUrlInput.disabled = true;
    
    // ハンバーガー＋スケボーアニメーション
    statusMessage.innerHTML = `
        <div class="burger-skate-anim">
            <div class="burger-skater">
                <div class="burger-arm"></div>
                <div class="burger-arm right"></div>
                <div class="burger-hand"></div>
                <div class="burger-hand right"></div>
                <div class="burger-body">
                    <div class="burger-seed"></div>
                    <div class="burger-face">
                        <span class="burger-eye"></span>
                        <span class="burger-eye"></span>
                        <span class="burger-mouth"></span>
                    </div>
                </div>
                <div class="burger-lettuce"></div>
                <div class="burger-tomato"></div>
                <div class="burger-patty"></div>
                <div class="burger-bottom"></div>
                <div class="burger-leg"></div>
                <div class="burger-leg right"></div>
                <div class="burger-shoe"></div>
                <div class="burger-shoe right"></div>
                <div class="burger-skateboard"></div>
                <div class="burger-wheel left"></div>
                <div class="burger-wheel right"></div>
            </div>
        </div>
        <p>処理中です。しばらくお待ちください。</p>
    `;
}

/**
 * ステータスに応じてUIを更新
 * @param {object} data ステータスデータ
 */
function updateStatus(data) {
    console.log('タスク状態更新:', data);
    // 全てのステップで同じアニメーションを表示
    statusMessage.innerHTML = `
        <div class="burger-skate-anim">
            <div class="burger-skater">
                <div class="burger-arm"></div>
                <div class="burger-arm right"></div>
                <div class="burger-hand"></div>
                <div class="burger-hand right"></div>
                <div class="burger-body">
                    <div class="burger-seed"></div>
                    <div class="burger-face">
                        <span class="burger-eye"></span>
                        <span class="burger-eye"></span>
                        <span class="burger-mouth"></span>
                    </div>
                </div>
                <div class="burger-lettuce"></div>
                <div class="burger-tomato"></div>
                <div class="burger-patty"></div>
                <div class="burger-bottom"></div>
                <div class="burger-leg"></div>
                <div class="burger-leg right"></div>
                <div class="burger-shoe"></div>
                <div class="burger-shoe right"></div>
                <div class="burger-skateboard"></div>
                <div class="burger-wheel left"></div>
                <div class="burger-wheel right"></div>
            </div>
        </div>
        <p>処理中です。しばらくお待ちください。</p>
    `;
    if (data.status === 'completed' || data.step === 'completed') {
        setTimeout(() => showComplete(data), 1000);
    }
}

/**
 * 完了表示
 * @param {object} data 完了データ
 */
function showComplete(data) {
    statusContainer.style.display = 'none';
    resultContainer.style.display = 'block';
    resultSuccess.style.display = 'block';
    resultError.style.display = 'none';
    
    // Notion URLがある場合はリンクを表示
    if (data.notion_url) {
        const notionLinkContainer = document.createElement('div');
        notionLinkContainer.className = 'notion-link';
        notionLinkContainer.innerHTML = `
            <p>登録したレシピを見る: 
                <a href="${data.notion_url}" target="_blank" rel="noopener noreferrer">
                    Notionで開く
                </a>
            </p>
        `;
        resultSuccess.appendChild(notionLinkContainer);
    }
    
    youtubeUrlInput.disabled = false;
    
    // ポーリングを停止
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

/**
 * エラー表示
 * @param {string} message エラーメッセージ
 */
function showError(message) {
    statusContainer.style.display = 'none';
    resultContainer.style.display = 'block';
    resultSuccess.style.display = 'none';
    resultError.style.display = 'block';
    
    youtubeUrlInput.disabled = false;
    
    errorMessage.textContent = message;
}

/**
 * UI状態をリセット
 */
function resetUI() {
    statusContainer.style.display = 'none';
    resultContainer.style.display = 'none';
    resultSuccess.style.display = 'none';
    resultError.style.display = 'none';
    
    // 入力フィールドのみ活性化し、ボタンの状態は変更しない
    youtubeUrlInput.disabled = false;
    
    // ポーリングをクリア
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
} 