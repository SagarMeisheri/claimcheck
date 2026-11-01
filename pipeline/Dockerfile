FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY claimcheck ./claimcheck
RUN pip install --no-cache-dir .
ENV PORT=8080
CMD exec uvicorn claimcheck.server:app --host 0.0.0.0 --port ${PORT} --workers 1
