# EGX Intelligence

A production-quality Windows desktop application for analysing Egyptian Exchange (EGX) Telegram channels using multimodal AI.

## What it does

- Connects to your personal Telegram account and loads all your chats, groups, and channels for the current session
- Lets you pick which channels to analyse and over how many days (1–5)
- Sends text, images, and audio transcripts to your chosen AI provider (Qwen Cloud by default)
- Returns a structured JSON report with ranked stock recommendations, achieved targets, and daily breakdowns
- Saves consolidated Markdown, HTML, and PDF reports plus the original AI response verbatim
- All credentials are encrypted with Windows DPAPI and stored only on your machine

---

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Windows 10/11 x64 | — | The only supported OS |
| Python | 3.12+ | Installed by bootstrap script |
| Node.js | 22 LTS | Installed by bootstrap script |
| Rust (stable-msvc) | 1.77+ | Installed by bootstrap script |
| Visual Studio Build Tools | 2022 | C++ Desktop workload — **manual install required** |
| WebView2 Runtime | Any | Ships with Windows 11; bootstrap warns if absent |
| NSIS | 3.x | For building the installer — **manual install required** |
| Git | Any | git-scm.com/download/win |

---

## Quick start (development)

```powershell
# 1. Clone
git clone https://github.com/ikverse/EGX-Analyser.git egx-intelligence
cd egx-intelligence

# 2. Bootstrap — installs Python, Node, Rust, checks VS Build Tools / WebView2 / NSIS
.\scripts\bootstrap-windows.ps1 -DesktopBuild

# 3. Restart your terminal (PATH changes from Rust/Node need a fresh shell)

# 4. Build the Windows installer
.\scripts\build-desktop.ps1

# Installer output:
#   desktop\src-tauri\target\release\bundle\nsis\EGX Intelligence_0.x.x_x64-setup.exe
```

The first run of `bootstrap-windows.ps1` will:
- Download and install Python 3.12.10 if needed
- Download and install Node.js 22 if needed
- Download and install Rust stable-msvc via `rustup-init.exe` if needed
- Check for VS Build Tools, WebView2, NSIS, and Git — print clear instructions for any that need manual action
- Create `.venv` and install all Python dependencies
- Install frontend npm dependencies
- Run the full test suite

---

## Telegram setup

1. Go to [my.telegram.org](https://my.telegram.org) → **API development tools**
2. Create an application — any name and description is fine
3. Copy **App api_id** and **App api_hash**
4. Open EGX Intelligence → **Settings**
5. Under **Telegram**, click **Add Telegram credentials** and paste them, then click **Save settings**
6. In the **Connect Telegram** section that appears, enter your phone number in international format (e.g. `+201012345678`) and press **Send code**
7. Enter the code Telegram sends you and press **Verify code**

After authorisation the session is saved in `%LOCALAPPDATA%\EGX Intelligence\telegram.session`. You will not need to log in again unless you change credentials.

> **Note:** This uses Telethon's MTProto user client, not a bot token. The app reads your personal Telegram dialogs.

---

## AI provider setup

Open **Settings** and select your provider from the dropdown.

### Qwen Cloud (default — best for Arabic + chart images)

1. Sign up at [dashscope.aliyuncs.com](https://dashscope.aliyuncs.com) or [dashscope-intl.aliyuncs.com](https://dashscope-intl.aliyuncs.com)
2. Create a **pay-as-you-go** API key under Model Studio
3. Paste the key in Settings → Qwen Cloud → **Add API key**
4. Select the endpoint that matches the key's region:
   - **China (Beijing):** `https://dashscope.aliyuncs.com/compatible-mode/v1`
   - **Singapore:** `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
   - **US (Virginia):** `https://dashscope-us.aliyuncs.com/compatible-mode/v1`
5. Press **Load available models** and select `qwen3-vl-plus` or another multimodal model

> Token Plan, Coding Plan, Qwen Chat, and expired temporary keys do **not** work. You need a pay-as-you-go Model Studio key.

### OpenRouter (free models available)

1. Sign up at [openrouter.ai](https://openrouter.ai) and create an API key
2. Select **OpenRouter** in Settings and paste the key
3. Press **Load available models** — filter shows only multimodal models that support structured output

### Hugging Face

1. Create an account at [huggingface.co](https://huggingface.co) and generate an access token
2. Select **Hugging Face** and paste the token
3. Load models — shows inference provider endpoints

### OpenAI

1. Create an API key at [platform.openai.com](https://platform.openai.com)
2. Select **OpenAI** and paste the key
3. Supported models: GPT-4o and GPT-4 series with vision

---

## Analysis prompt

The built-in prompt instructs the AI to extract EGX trade recommendations from Arabic and English Telegram content, preserving prices and tickers exactly as posted.

You can override it in **Settings → Primary analysis prompt**. The required JSON output structure is always enforced regardless of the custom prompt.

The expected JSON structure:

```json
{
  "analysis_period": "Last 3 Days",
  "top_consolidated_recommendations": [
    {
      "stock_code": "MFPC",
      "stock_name_en": "Mobaco",
      "stock_name_ar": "موبكو",
      "mention_count": 3,
      "rank": 1,
      "status": "active",
      "data_points": [
        {
          "date": "2026-07-12",
          "source": "CFI",
          "buy_price": 37.25,
          "target_1": 38.70,
          "target_2": 40.00,
          "stop_loss": 35.55,
          "support": null,
          "resistance": null,
          "expected_return_pct": 3.18,
          "risk_pct": -1.84
        }
      ],
      "analysis_summary_ar": "توصية شراء قوية"
    }
  ],
  "achieved_targets": [],
  "text_based_categories": {
    "most_important_stocks": [],
    "trading_stocks": [],
    "watchlist_stocks": []
  },
  "daily_breakdown": {
    "2026-07-12": { "total_mentions": 3, "top_stock_of_day": "MFPC" }
  }
}
```

---

## Running an analysis

1. Go to **Channels**
2. Press **Load my Telegram chats** — loads your current-session chat list (not persisted after closing the app)
3. Click **Select** next to any channel you want to analyse
4. Use the **Analysis window** slider to set how many days back to look (1–5)
5. Press **Analyze selected chats**
6. When complete, report paths appear on screen and the Reports page updates

Reports are saved to `%LOCALAPPDATA%\EGX Intelligence\storage\reports\<date>\`.

---

## Building the installer

```powershell
# Development build (no signing required)
.\scripts\build-desktop.ps1

# Release build (requires signing key set up first)
.\scripts\enable-updater.ps1 -GithubRepo ikverse/EGX-Analyser
.\scripts\build-desktop.ps1 -Release
```

The build pipeline:
1. Installs Python dependencies
2. Generates desktop icons
3. Packages the FastAPI sidecar with PyInstaller (`egx-intelligence-api.exe`)
4. Copies the binary to `desktop\src-tauri\binaries\`
5. Runs `cargo check` as a fast-fail gate
6. Runs `npm run tauri build`
7. Outputs `EGX Intelligence_<version>_x64-setup.exe` under `desktop\src-tauri\target\release\bundle\nsis\`

### GitHub Actions release

Tag a commit with `v0.x.x` and push — the workflow builds and publishes automatically:

```bash
git tag v0.1.35
git push origin v0.1.35
```

The release workflow requires these GitHub secrets:
- `TAURI_SIGNING_PRIVATE_KEY` — base64-encoded minisign private key
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — key password

---

## Data and privacy

| What | Where |
|---|---|
| Database | `%LOCALAPPDATA%\EGX Intelligence\intelligence.db` (SQLite) |
| API keys and secrets | `%LOCALAPPDATA%\EGX Intelligence\secrets.json` (DPAPI-encrypted) |
| Config | `%LOCALAPPDATA%\EGX Intelligence\.env` |
| Telegram session | `%LOCALAPPDATA%\EGX Intelligence\telegram.session` |
| Reports | `%LOCALAPPDATA%\EGX Intelligence\storage\reports\` |
| Images | `%LOCALAPPDATA%\EGX Intelligence\storage\images\` |
| Analysis traces | `%LOCALAPPDATA%\EGX Intelligence\storage\analysis-traces\` |
| Diagnostics log | `%LOCALAPPDATA%\EGX Intelligence\logs\api-diagnostics.jsonl` |

Full application updates preserve all of the above. No data is sent to any server except the AI provider API calls you configure.

API keys, Telegram credentials, and message content are **never** written to the diagnostics log.

---

## Troubleshooting

### App shows "Starting your local intelligence workspace…" indefinitely

The Python sidecar failed to start. Check:
- `%LOCALAPPDATA%\EGX Intelligence\logs\api-diagnostics.jsonl` for errors
- In Settings → **View recent diagnostics** if the engine starts eventually

Common causes:
- Port 8000 already in use — `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F`
- Missing Python dependencies — run `scripts\bootstrap-windows.ps1 -DesktopBuild` again

### Qwen API key is rejected (401/403)

- Use a **pay-as-you-go Model Studio** key, not a Token Plan or Qwen Chat key
- The key region and endpoint must match — a Beijing key cannot call the Singapore endpoint
- Keys from expired trials or limited plans will not work

### "A background collection is already running"

The 60-second background collector is active. Wait a few seconds and try again.

### Telegram `FloodWaitError` or `AuthKeyError`

Telegram rate-limited your account or the session expired. Wait the specified seconds, then reconnect in Settings. If the error persists, delete `telegram.session` from `%LOCALAPPDATA%\EGX Intelligence\` and reconnect.

### PDF Arabic text is garbled

Install Arial font if not already present (`C:\Windows\Fonts\arial.ttf`). The PDF renderer falls back to Courier if Arial is missing, which does not support Arabic glyphs.

### `cargo check` fails in `build-desktop.ps1`

Ensure the Rust `stable-msvc` toolchain and VS Build Tools with the C++ Desktop workload are installed:

```powershell
rustup toolchain install stable-msvc
rustup default stable-msvc
```

### Tests fail after pulling new changes

```powershell
.\scripts\bootstrap-windows.ps1 -DesktopBuild
```

---

## Development

```powershell
# Run backend only (hot-reload)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Run frontend dev server (connects to the backend above)
cd desktop && npm run dev

# Run tests
.venv\Scripts\python.exe -m pytest tests/ -v

# Type-check TypeScript
cd desktop && node_modules\.bin\tsc --noEmit
```

---

## Disclaimer

EGX Intelligence processes and summarises publicly available Telegram content. Output is provided for research and informational purposes only and does not constitute investment advice. Always verify recommendations independently before making any financial decisions.
