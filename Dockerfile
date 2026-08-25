FROM python:3.12-slim

# Create non-root user
RUN useradd -m -s /bin/bash copilot

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY graph.py db.py schema.sql ./
COPY mcp_servers/ ./mcp_servers/

# Set permissions
RUN chown -R copilot:copilot /app

# Switch to non-root user
USER copilot

# Expose port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "print('ok')"

# Start command
CMD ["python", "-m", "uvicorn", "graph:app", "--host", "0.0.0.0", "--port", "8000"]
