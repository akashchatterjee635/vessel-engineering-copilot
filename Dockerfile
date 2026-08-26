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
COPY mlops/ ./mlops/

# Create a stub cemg package if not mounted externally
# In production, mount the real cemg package as a volume or install via pip
RUN mkdir -p cemg && \
    echo "" > cemg/__init__.py && \
    printf 'class SqliteStorage:\n    def __init__(self, db_path="cemg_memory.db"): pass\n' > cemg/storage.py && \
    printf 'def build_memory_block(*a, **kw): return ""\ndef peek_signature_status(*a, **kw): return {"action_signature": "stub", "status_before": "CLEAR"}\ndef store_experience(*a, **kw): pass\n' > cemg/memory.py

# Set permissions
RUN chown -R copilot:copilot /app

# Switch to non-root user
USER copilot

# Expose port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "print('ok')"

# Default: run the graph module directly (can be overridden)
CMD ["python", "-c", "import graph; print('Vessel Copilot loaded successfully')"]
