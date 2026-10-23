# 本体(FastAPI)のイメージ。ビルドコンテキストは app/
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo

WORKDIR /app

# LightGBM の Linux 版が使う OpenMP(libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# ライブラリの版は constraints.txt で固定する(本体・モデル作成と同じ版)
COPY constraints.txt ./
# 特徴量の共通パッケージ(app/features)を本体と一緒に入れる
COPY features features
COPY backend/pyproject.toml backend/
COPY backend/smdx_api backend/smdx_api
RUN pip install --no-cache-dir -c constraints.txt -e ./features -e ./backend

COPY backend backend
WORKDIR /app/backend

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn --factory smdx_api.main:create_app --host 0.0.0.0 --port 8000"]
