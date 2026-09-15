import os

os.makedirs("k8s", exist_ok=True)

manifests = {
    "k8s/namespace.yaml": """apiVersion: v1
kind: Namespace
metadata:
  name: vessel-copilot
""",
    "k8s/configmap.yaml": """apiVersion: v1
kind: ConfigMap
metadata:
  name: copilot-config
  namespace: vessel-copilot
data:
  VESSEL_COPILOT_DB: "vessel_copilot.db"
  VESSEL_COPILOT_MODEL: "gpt-5.4-nano"
  MCP_SERVERS_ENABLED: "true"
  MCP_TELEMETRY_URL: "http://mcp-telemetry:8001/mcp"
""",
    "k8s/secret.yaml": """apiVersion: v1
kind: Secret
metadata:
  name: copilot-secrets
  namespace: vessel-copilot
type: Opaque
data:
  # OPENAI_API_KEY will be injected by the CI pipeline via envsubst
  OPENAI_API_KEY: \
""",
    "k8s/mcp-telemetry.yaml": """apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-telemetry
  namespace: vessel-copilot
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mcp-telemetry
  template:
    metadata:
      labels:
        app: mcp-telemetry
    spec:
      containers:
        - name: mcp-telemetry
          image: \\.azurecr.io/mcp-telemetry:\
          ports:
            - containerPort: 8001
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "250m"
              memory: "256Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-telemetry
  namespace: vessel-copilot
spec:
  selector:
    app: mcp-telemetry
  ports:
    - protocol: TCP
      port: 8001
      targetPort: 8001
""",
    "k8s/copilot-app.yaml": """apiVersion: apps/v1
kind: Deployment
metadata:
  name: copilot-app
  namespace: vessel-copilot
spec:
  replicas: 3
  selector:
    matchLabels:
      app: copilot-app
  template:
    metadata:
      labels:
        app: copilot-app
    spec:
      containers:
        - name: copilot-app
          image: \\.azurecr.io/copilot-app:\
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: copilot-config
          env:
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: copilot-secrets
                  key: OPENAI_API_KEY
          resources:
            requests:
              cpu: "200m"
              memory: "512Mi"
            limits:
              cpu: "500m"
              memory: "1Gi"
          livenessProbe:
            httpGet:
              path: /
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: db-data
              mountPath: /app/data
      volumes:
        - name: db-data
          persistentVolumeClaim:
            claimName: copilot-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: copilot-app
  namespace: vessel-copilot
spec:
  type: LoadBalancer
  selector:
    app: copilot-app
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8000
""",
    "k8s/pvc.yaml": """apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: copilot-pvc
  namespace: vessel-copilot
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
""",
    "k8s/hpa.yaml": """apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: copilot-app-hpa
  namespace: vessel-copilot
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: copilot-app
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
""",
}

for path, content in manifests.items():
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

print("K8s manifests created successfully.")
