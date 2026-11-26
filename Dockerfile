# MigrateRight - pipeline + Streamlit dashboard image
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY app/ app/
COPY config/ config/
COPY sql/ sql/
COPY data/legacy/ data/legacy/
COPY .streamlit/ .streamlit/

EXPOSE 8540
# Default: run the pipeline, then serve the sign-off dashboard
CMD ["sh", "-c", "python -m src.pipeline && streamlit run app/dashboard.py --server.port 8540 --server.address 0.0.0.0"]
