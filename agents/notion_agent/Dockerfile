# ベースイメージを選択
FROM python:3.12-slim

# 環境変数
# Pythonがpycファイルを作成しないようにする
ENV PYTHONDONTWRITEBYTECODE 1
# Pythonが標準出力と標準エラーをバッファリングしないようにする
ENV PYTHONUNBUFFERED 1
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

# 作業ディレクトリ設定
WORKDIR /app

# OS依存パッケージのインストール
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Poetryのインストール
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN poetry --version # インストールされたバージョンを確認

# 最初に依存関係ファイルだけコピーしてインストール 
COPY pyproject.toml poetry.lock /app/

# 依存関係のインストール
RUN poetry install --no-root

# アプリケーションコードをコピー
COPY . /app/

# ポート公開
EXPOSE 5002

# コンテナ起動コマンド（waitress-serveを使用）
CMD ["poetry", "run", "waitress-serve", "--host=0.0.0.0", "--port=5002", "main:app"]
