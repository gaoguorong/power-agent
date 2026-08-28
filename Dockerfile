FROM python:3.10-slim

WORKDIR /app

COPY packages/ /app/packages/

COPY requirements.txt .

RUN pip install --no-index --find-links=/app/packages/ \
    pandapower==3.4.0 \
    pandas>=2.0.0 \
    numpy>=1.24.0 \
    requests>=2.28.0

# 后端分层目录（类 MVC）
COPY main.py ./
COPY config/ ./config/
COPY controllers/ ./controllers/
COPY schemas/ ./schemas/
COPY services/ ./services/
COPY models/ ./models/
COPY agents/ ./agents/
COPY tools/ ./tools/
COPY skills/ ./skills/
COPY mcp/ ./mcp/

# 前端构建产物（SPA 静态托管）
COPY frontend/dist/ ./frontend/dist/

EXPOSE 8000

CMD ["python", "main.py"]