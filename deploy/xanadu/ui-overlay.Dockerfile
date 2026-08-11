ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY dist /app/frontend/dist
