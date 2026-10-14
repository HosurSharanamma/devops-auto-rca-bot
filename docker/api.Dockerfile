FROM python:3.12-slim

# curl needed for the container HEALTHCHECK below
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install CPU-only PyTorch FIRST, from PyTorch's own CPU wheel index. Without
# this, pip pulls the default GPU build (via sentence-transformers' torch
# dependency), which drags in several GB of NVIDIA CUDA libraries that are
# useless here -- no GPU on this laptop, no GPU access inside the container
# either way. This single line is what keeps the image from downloading
# several unnecessary gigabytes and taking hours to build.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image at build time. Without this,
# sentence-transformers silently downloads it from huggingface.co on the
# FIRST request after every pod start -- fine on a laptop, a real problem
# on EKS where pods restart/scale and may have no outbound internet at all.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY api/ ./api/
COPY rag/ ./rag/
COPY models/ ./models/
COPY utils/ ./utils/
COPY data/ ./data/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
