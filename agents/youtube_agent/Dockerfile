# ベースイメージを選択
FROM python:3.12-slim

# 環境変数
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

# OS依存パッケージのインストール (Whisperに必要なffmpegなど)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Poetryのインストール
RUN curl -sSL https://install.python-poetry.org | python3 -

# 作業ディレクトリ設定
WORKDIR /app

# 最初に依存関係ファイルだけコピーしてインストール
COPY pyproject.toml poetry.lock ./

# 依存関係をインストール
RUN poetry install --no-root

# アプリケーションコードをコピー
COPY . /app/

# ポート公開 (Flaskのデフォルトは5000)
EXPOSE 5000

# コンテナ起動コマンド（waitress-serveを使用）
CMD ["poetry", "run", "waitress-serve", "--host=0.0.0.0", "--port=5000", "main:app"] 