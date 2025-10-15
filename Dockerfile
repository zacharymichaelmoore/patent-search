FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY api ./api
COPY frontend ./frontend

EXPOSE 8090

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8090", "--reload"]
