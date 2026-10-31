# Optional REST API (the dashboard itself is static and needs no server).
#   docker build -t whips-api .
#   docker run -p 8000:8000 -e WHIPS_DATA=https://<user>.github.io/<repo>/data/data.json whips-api
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY whips ./whips
RUN pip install --no-cache-dir ".[api]"
ENV WHIPS_DATA=/app/data/data.json
EXPOSE 8000
CMD ["uvicorn", "whips.api:app", "--host", "0.0.0.0", "--port", "8000"]
