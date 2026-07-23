# Auto-RCA Bot — Live/Public Version

A free, publicly hostable version of the Auto-RCA Bot. No local LLM or
GPU required — anyone can open the link in a browser and paste a Jenkins
failure log.

## What's different from the offline capstone version
See the table in the main repo's conversation history / PR description, in short:
- **LLM:** [Groq](https://groq.com) hosted API (free tier, OpenAI-compatible)
  instead of local LM Studio + Mistral.
- **Embeddings:** ChromaDB's built-in ONNX MiniLM embedder instead of
  sentence-transformers + torch — same model family, ~15x smaller install,
  which matters on a free hosting tier's memory limit.
- **Vector store:** in-memory, rebuilt from the bundled 40-log dataset on
  startup (a couple of seconds) instead of a persistent on-disk ChromaDB.
- **Rate limiting:** a simple per-browser-session cap, since this is a
  public tool sharing one API key. It's a courtesy speed bump, not
  airtight abuse protection — see "Known limitations" below.

## 1. Get a free Groq API key
1. Go to <https://console.groq.com/keys> and sign up (free).
2. Create an API key.
3. Note the default model in `live/rca_generation.py` is
   `llama-3.3-70b-versatile`. Check <https://console.groq.com/docs/models>
   for the current list of free-tier models if that one has been retired —
   Groq's lineup changes over time.

## 2. Run it locally first (recommended before deploying)
```bash
cd devops-auto-rca-bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r live/requirements.txt

export GROQ_API_KEY=your_key_here     # Windows (PowerShell): $env:GROQ_API_KEY="your_key_here"
streamlit run live/app.py
```
Opens at `http://localhost:8501`. Paste a sample log and confirm you get a
grounded root cause back.

## 3. Deploy for free on Streamlit Community Cloud
1. Push this repo (including the `live/` folder) to GitHub — already done
   if you're working from the PR in this repo.
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. Click **New app** → pick this repo → set:
   - **Main file path:** `live/app.py`
4. Before deploying (or after, in app settings), add your secret:
   - Go to **Advanced settings → Secrets** and add:
     ```toml
     GROQ_API_KEY = "your_key_here"
     ```
5. Deploy. First load will take a minute or two to install dependencies
   and download the ONNX embedding model; subsequent loads are fast.
6. You'll get a public URL like `https://your-app-name.streamlit.app` —
   share that link with anyone.

## Known limitations (disclosed, not hidden)
- **Rate limiting is per-session, not per-IP.** A determined user could
  open multiple browser sessions to bypass the cap. For a hobby/portfolio
  deployment this is an acceptable tradeoff; if usage grows, consider
  Streamlit's newer built-in rate-limiting options or moving the LLM call
  behind a small backend with IP-based limiting.
- **The knowledge base is the same small 40-log synthetic dataset** used
  in the capstone. It demonstrates the RAG pattern well but isn't a large
  real-world incident corpus. Swap in `data/synthetic_jenkins_logs.json`
  (or extend `scripts/generate_synthetic_data.py`) if you want to grow it.
- **Groq's free tier has rate limits** (requests/day and tokens/minute,
  and these change over time) — check <https://console.groq.com/docs/rate-limits>
  for current numbers. If the app suddenly starts returning fallback
  errors, that's the most likely cause.
- **No persistence across restarts** by design — nothing a visitor pastes
  is ever written to disk or a database. This is a privacy feature, not a
  bug, but it does mean there's no usage history/analytics unless you
  deliberately add them.
