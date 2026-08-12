ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY app /app/app
COPY frontend/dist /app/frontend/dist
