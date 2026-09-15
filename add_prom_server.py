with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """import streamlit as st

def stream_string(text: str, delay: float = 0.04):"""

replacement = """import streamlit as st
from prometheus_client import start_http_server

@st.cache_resource
def start_metrics_server():
    try:
        start_http_server(9090)
        print("Prometheus metrics server started on port 9090")
    except OSError:
        pass # Already started

start_metrics_server()

def stream_string(text: str, delay: float = 0.04):"""

if target in content:
    content = content.replace(target, replacement)
    with open("app.py", "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
