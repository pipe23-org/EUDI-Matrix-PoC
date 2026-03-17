FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml ./
RUN uv sync
COPY app.py .
EXPOSE 8090
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
