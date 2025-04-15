# recipe_agent/Dockerfile

# ベースイメージを選択 (YouTube Agentと同じPythonバージョン)
FROM python:3.12-slim

# 環境変数 (Poetry関連は共通)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

# OS依存パッケージのインストール (ffmpeg を含める)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Poetryのインストール
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN poetry --version # Verify installed version

# 作業ディレクトリ設定
WORKDIR /app

# 最初に依存関係ファイルだけコピーしてインストール
COPY pyproject.toml poetry.lock /app/

# 依存関係のインストール
RUN poetry install --no-root

# アプリケーションコードをコピー
COPY . /app/

# ポート公開 (recipe_agent/main.py で指定した 5001)
EXPOSE 5001

# コンテナ起動コマンド (recipe_agent/main.py の app を起動)
CMD ["poetry", "run", "waitress-serve", "--host=0.0.0.0", "--port=5001", "main:app"] 