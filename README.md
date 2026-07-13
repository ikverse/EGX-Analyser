# EGX Stock Intelligence

Production-oriented multimodal intelligence for Egyptian-stock Telegram channels. It persists raw content, extracts structured signals from Arabic text and chart images, aggregates consensus, generates reports, and presents a local Streamlit dashboard.

## Start

1. Copy `.env.example` to `.env`, then set Telegram credentials and one cloud AI provider key. Qwen Cloud is the default, with OpenRouter, Hugging Face Inference Providers, and OpenAI also supported; the desktop Settings page can discover the compatible models dynamically.
2. On Windows, run `powershell -ExecutionPolicy Bypass -File scripts/bootstrap-windows.ps1` once to install Python, Docker Desktop, and project packages. Pass `-SkipDocker` if Docker is already installed.
3. Run `docker compose up --build`.
4. Open `http://localhost:8501`; the API docs are at `http://localhost:8000/docs`.

Run database migrations in a deployment with `alembic upgrade head`. For a local non-container trial, install `.[dev]` and run `uvicorn app.main:app --reload`.

## Operations

In the dashboard, open **Settings** to add Telegram channel usernames and use the **Active** toggle to choose exactly which channels are analyzed. The worker checks active channels every minute and creates a daily report. `TELEGRAM_CHANNELS` remains available as an initial fallback before channels are added in the dashboard. Telegram must be authorized once for the session configured by `TELEGRAM_SESSION`. Store `.session` files as secrets and restrict access to the storage volume. The API has no login and is intended only for local, single-user use.

## Scope

The application produces research signals, not investment advice. Validate all extracted recommendations against original messages before trading.

## Desktop application

For a normal Windows application with an icon, native window, and installer, see `docs/DESKTOP.md`. Once installed, it runs a bundled local API engine and does not require Docker or a browser.

## Cloud AI providers

The desktop app does not download AI models. **Qwen Cloud** is the default provider and uses `qwen3-vl-plus` for Arabic text and chart-image analysis through Alibaba Cloud Model Studio. Use a pay-as-you-go Model Studio API key and the endpoint for the same region: Beijing `https://dashscope.aliyuncs.com/compatible-mode/v1`, Singapore `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, or US `https://dashscope-us.aliyuncs.com/compatible-mode/v1`. OpenRouter, Hugging Face Inference Providers, and OpenAI remain available. Audio transcription and semantic embedding search currently use OpenAI when those features are required; text and image recommendation analysis works with every listed cloud provider.
