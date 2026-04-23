# Playwright公式イメージを使うとChromiumが最初から入っているので楽
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# requirements.txt 先にコピーして依存関係キャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体
COPY . .

# Railway が PORT 環境変数を渡してくるのでそれを使う
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# 起動コマンド
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
