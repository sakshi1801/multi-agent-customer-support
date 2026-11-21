# Deploying for free

The app is one container: FastAPI, the demo page, the embedding model (baked into the image) and two
SQLite files. It needs **one free model key** (Groq) and no database server. CI builds the image and
smoke-tests the running container on every push, so the Dockerfile is known to work.

## Environment variables the host needs

| Variable | Value | Why |
|---|---|---|
| `GROQ_API_KEY` | your free key from console.groq.com | the language model |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` (best router in our evaluation) or `openai/gpt-oss-120b` | which model |
| `SUPERVISOR_MODE` | `plan` (already the image default) | one routing call per message |
| `TOKEN_SECRET` | a long random string | signs customer login tokens |
| `AGENT_API_KEY` | a long random string | the human-agent console password |
| `LLM_FALLBACKS` | `openrouter` + `OPENROUTER_API_KEY` (optional) | automatic fallback when Groq's free tier is rate limited |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` (optional) | free developer plan | traces every supervisor decision and tool call |

Generate the two secrets with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Never commit them: put them in the host's secrets settings.

## Option A: Hugging Face Spaces (recommended: free CPU with 16 GB RAM, no card)

1. Create a free account at huggingface.co, then **New Space**, SDK **Docker**, visibility Public.
2. In the Space's **Settings > Variables and secrets**, add the variables above as *secrets*.
3. Push this repository to the Space. The Space needs a `README.md` with the YAML header in
   [`deploy/hf-space-README.md`](../deploy/hf-space-README.md), so push it as the Space's README:
   ```bash
   git clone https://huggingface.co/spaces/<your-user>/<space-name> space && cd space
   cp -r ../multi-agent-customer-support/{app,data,requirements.txt,Dockerfile,.dockerignore} .
   cp ../multi-agent-customer-support/deploy/hf-space-README.md README.md
   git add -A && git commit -m "Deploy" && git push
   ```
4. The Space builds the image (a few minutes) and serves the demo page at
   `https://<your-user>-<space-name>.hf.space`.

## Option B: Render (free web service)

Create a **Web Service** from the GitHub repo with *Runtime: Docker* and the same environment variables.
Free instances have 512 MB of RAM, which is tight for the embedding model; if it restarts, use Option A.

## What to know about free hosting

* Free instances sleep when idle: the first request after a pause takes about 30 seconds.
* The SQLite files live on the instance disk and reset on redeploy. That is fine for a demo (the demo
  accounts and orders are re-created at startup); use a managed database for anything real.
* Groq's free tier limits each model to roughly 8K tokens a minute and 200K a day, plenty for a demo.
