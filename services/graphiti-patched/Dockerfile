FROM zepai/graphiti:latest
COPY zep_graphiti.py /app/graph_service/zep_graphiti.py
COPY ingest.py /app/graph_service/routers/ingest.py
USER root
RUN chmod 0644 /app/graph_service/zep_graphiti.py /app/graph_service/routers/ingest.py
