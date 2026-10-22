FROM python:3.12-slim
WORKDIR /workspace
COPY requirements.txt ./
COPY rag-mcp/requirements.txt ./rag-mcp/requirements.txt
RUN python -m pip install --no-cache-dir -r rag-mcp/requirements.txt
COPY rag-mcp/rag_mcp ./rag-mcp/rag_mcp
COPY rag-mcp/data ./rag-mcp/data
ENV PYTHONPATH="/workspace/rag-mcp" PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["sh", "-c", "python -m rag_mcp.cli init-db && uvicorn rag_mcp.server:app --host 0.0.0.0 --port 8001"]
