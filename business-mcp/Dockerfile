FROM python:3.12-slim
WORKDIR /workspace
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY business-mcp/business_mcp ./business-mcp/business_mcp
ENV PYTHONPATH="/workspace/business-mcp" PYTHONUNBUFFERED=1
EXPOSE 8002
CMD ["uvicorn", "business_mcp.server:app", "--host", "0.0.0.0", "--port", "8002"]
