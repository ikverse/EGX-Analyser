# Architecture

FastAPI receives authenticated requests and exposes a stable REST boundary. `MessageService` stores raw immutable Telegram content before `AIAnalysisService` performs structured multimodal extraction. A Celery worker schedules collection and reporting, keeping network and model latency out of API requests.

PostgreSQL is the source of truth. `channels`, `messages`, `images`, `stocks`, and `recommendations` are normalized; `embeddings` uses pgvector for semantic retrieval. The current search endpoint uses text search as a reliable baseline; adding OpenAI embeddings plus pgvector distance ordering belongs in the same repository layer.

Prompt files live in `app/ai/prompts/` and are versioned with the application. The OpenAI model is an environment setting because model availability depends on the deployment account.
