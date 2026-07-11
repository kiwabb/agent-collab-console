FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY benchmark/ ./benchmark/

RUN mkdir -p /var/lib/agent-collab \
    && ln -s /var/lib/agent-collab/benchmark.db /app/benchmark.db

EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
