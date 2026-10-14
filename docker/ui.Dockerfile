FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

# Same fix as api.Dockerfile: force CPU-only PyTorch before the rest of
# requirements.txt installs, since that file is shared with the API and
# pulls in sentence-transformers (and therefore torch) even though the UI
# itself never uses it -- without this line pip grabs the GPU build and
# downloads several GB of unused NVIDIA CUDA packages.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY ui/ ./ui/
COPY data/evaluation_report.json ./data/evaluation_report.json

ENV PYTHONUNBUFFERED=1
EXPOSE 8501

CMD ["streamlit", "run", "ui/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
