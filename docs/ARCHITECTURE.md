# Architecture

EGX Analyzer is a local Windows desktop application. A Tauri shell hosts the React interface and starts a bundled FastAPI sidecar bound to `127.0.0.1:8000`. Runtime data is stored in a local SQLite database under `%LOCALAPPDATA%\EGX Intelligence`; no PostgreSQL, Redis, Celery, Streamlit, or browser deployment is required.

## Analysis flow

1. The background Telegram collector saves new messages and media without invoking AI.
2. The user selects chats, a target-date mode, and input types, then explicitly starts analysis.
3. FastAPI resolves the source window using Cairo calendar boundaries and loads the selected text, images, and available voice-note transcripts.
4. `AIAnalysisService` sends one consolidated multimodal request to the configured Qwen Cloud endpoint or optional local Ollama model.
5. The response is normalized, matched to Telegram message IDs, enriched from the local EGX catalog when a safe ticker match exists, and saved as a Results run.
6. Markdown, HTML, the original provider response, and a local diagnostic trace are retained for traceability. The application does not generate PDF files.

Only one model analysis can run at a time. A user can stop the active request from the interface. Telegram refresh and background collection never start model analysis.

## Data and configuration

- SQLite: `%LOCALAPPDATA%\EGX Intelligence\intelligence.db`
- Public settings: `%LOCALAPPDATA%\EGX Intelligence\.env`
- DPAPI-encrypted secrets: `%LOCALAPPDATA%\EGX Intelligence\secrets.json`
- Telegram session: `%LOCALAPPDATA%\EGX Intelligence\telegram.session`
- Reports and traces: `%LOCALAPPDATA%\EGX Intelligence\storage`
- Diagnostics: `%LOCALAPPDATA%\EGX Intelligence\logs`

The canonical prompts live in `app/ai/prompts/`. User-managed Include and Exclude phrases are appended without replacing the canonical date, source, identity, and output contract.

## Compatibility

Saved Results remain JSON-backed in the `reports` table. New fields use defaults when older rows do not contain them. The catalog is an enrichment layer: a failed, missing, or unsafe lookup leaves the source-provided stock identity intact and does not fail analysis.
