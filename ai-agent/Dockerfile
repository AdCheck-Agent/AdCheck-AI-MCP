FROM python:3.12-slim
WORKDIR /workspace
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY ai-agent/app ./ai-agent/app
ENV PYTHONPATH="/workspace/ai-agent" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "app.main"]
