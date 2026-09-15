with open("k8s/copilot-app.yaml", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace(
    "image: \\.azurecr.io/copilot-app:          ports:",
    "image: vesselcopilot.azurecr.io/copilot-app:latest\n          ports:",
)
with open("k8s/copilot-app.yaml", "w", encoding="utf-8", newline="\n") as f:
    f.write(c)

with open("k8s/mcp-telemetry.yaml", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace(
    "image: \\.azurecr.io/mcp-telemetry:          ports:",
    "image: vesselcopilot.azurecr.io/mcp-telemetry:latest\n          ports:",
)
with open("k8s/mcp-telemetry.yaml", "w", encoding="utf-8", newline="\n") as f:
    f.write(c)
