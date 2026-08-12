ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN rm -rf /app/data
COPY data /app/data
