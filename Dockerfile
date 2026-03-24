FROM python:3.11-slim

WORKDIR /app

COPY app.py .

RUN pip install --no-cache-dir flask huggingface_hub

RUN mkdir -p /data/uploads

CMD ["python", "app.py"]
