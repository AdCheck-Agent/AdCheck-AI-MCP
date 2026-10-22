FROM python:3.12-slim
WORKDIR /workspace
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY rag-mcp/rag_mcp ./rag-mcp/rag_mcp
ENV PYTHONPATH="/workspace/rag-mcp" PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "rag_mcp.server:app", "--host", "0.0.0.0", "--port", "8001"]
