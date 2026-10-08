FROM python:3.14-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY run_api.py ./
COPY deploy/docker/run_backend.py ./docker_entrypoint.py
EXPOSE 8000
CMD ["/app/.venv/bin/python", "run_api.py", "--host", "0.0.0.0", "--port", "8000"]
