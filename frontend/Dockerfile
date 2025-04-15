FROM python:3.12-slim

# 環境変数
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

# タイムゾーンを日本に設定
ENV TZ=Asia/Tokyo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# OS依存パッケージのインストール
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Poetryのインストール
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN poetry --version # インストールされたバージョンを確認

WORKDIR /app

# 最初に依存関係ファイルだけコピーしてインストール
COPY pyproject.toml poetry.lock /app/

# 依存関係のインストール
RUN poetry install --no-root

# アプリケーションコードをコピー
COPY . /app/

# コンテナ内部ポート
EXPOSE 5003

# アプリケーション実行（waitress-serveを使用）
CMD ["poetry", "run", "waitress-serve", "--host=0.0.0.0", "--port=5003", "main:app"] 