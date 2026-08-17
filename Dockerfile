FROM python:3.11-slim

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="due-diligence-assistant" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY frontend/dist ./frontend/dist
RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
