# Changelog

## v0.1.78
- Selects the applicable EGX trading session in Africa/Cairo time: the current session before or during market hours, otherwise the next Sunday-through-Thursday session.
- Prevents empty analysis runs from creating saved Results entries and records detailed local diagnostics for empty input windows.
- Removes target-hit and previous-recommendation updates from the model input, including text, captions, and selected audio transcripts.

## v0.1.77
- Added per-run analysis timing across collection, media preparation, AI requests, catalog enrichment, report creation, and persistence.
- Added retry audit files and Results status that confirm whether an automatic correction retry passed validation or still has warnings.

## v0.1.76
- Redesigned client-inquiry cards into a smaller, Arabic-first right-to-left layout with compact price-level blocks.

## v0.1.75
- Lists every model reported by the selected AI provider instead of filtering by modality or provider-specific capabilities.
- Fixed Channels selection highlighting by normalizing Telegram handles and made rapid or bulk selections update consistently.
- Refined the Telegram chat table with a higher-contrast header and clearer selected-row styling.

## v0.1.74
- Refined the Results tab with a saved-run overview, clear result totals, stronger empty-state guidance, and expanded-run metadata.
- Improved visual hierarchy for nested recommendation and client-inquiry sections without changing analysis data or actions.

## v0.1.73
- Prevented marked client inquiry messages from leaking into the active recommendation table while preserving valid source rows.
- Redesigned client inquiry cards and clarified their question, assessment, levels, and scenario details.
- Streamlined Channels selection, corrected Results action-column alignment, and clarified supplementary extraction guidance in Settings.

## v0.1.72
- Redesigned Channels into a session-focused workflow with chat filtering, bulk selection, and persisted analysis choices.
- Keeps an active analysis visible while navigating between tabs and refreshes Results automatically when it completes.
- Simplified Settings with a configuration overview, full-app updates only, and clearer Telegram and support actions.
- Removed the Reports navigation page and aligned Results action columns.

## v0.1.71
- Corrected Arabic detection for past recommendation captions and customer-inquiry replies.
- Enforced source-message traceability for both recommendation and inquiry model output, with one automatic correction retry when the model mixes the two lists.
- Shows non-blocking model-output audit warnings in Results while retaining every returned analysis response.
- Uses the last 24 hours for normal next-day analysis and includes Thursday through the Analyze moment when preparing recommendations for Sunday.

## v0.1.70
- Expands selected-chat evidence windows to two days for next-day and historical analysis.
- Excludes image posts whose captions mark them as past recommendations before model submission and records them in each trace.
- Accepts only literal `T+1` as a prior-date recommendation exception and labels those data points accordingly.

## v0.1.69
- Saves a dedicated local trace folder before every selected-chat model request, containing only the chosen date-window and media types.
- Records the final provider prompt, selected source files, optimized image bytes actually sent to the model, and the returned JSON response in the same trace folder.
- Keeps the trace available when an AI provider rejects, fails, or times out on a request.

## v0.1.68
- Added an explicit two-list model workflow: customer inquiry replies are returned only in the separate client-inquiries output, while cleaned recommendations are returned only in the main table.
- Added BUY/SELL classification and per-source Arabic notes for dated narrative or chart recommendations without a standard table.
- Preserved every model-returned recommendation data point as its own Results and report row; source values are no longer merged or replaced with later values.

## v0.1.67
- Added Local Ollama as a second analysis-provider option alongside the existing cloud providers. It uses the same analysis prompt, JSON contract, and Results flow without requiring an API key.
- Added local vision-model discovery for Ollama. `qwen3-vl:4b` is the default local model; the app only lists models already installed on the computer.
- Added separately saved local Ollama model and service-URL settings, preserving the cloud provider configuration when switching providers.
- Fixed the release version mismatch by synchronizing the FastAPI version with the desktop, Node, Rust, and Python package versions.

## v0.1.66
- Made the AI response the sole authority for separating active recommendations from client inquiry replies; the desktop app no longer reclassifies or discards either result type.
- Kept the EGX catalog entirely out of the model request. It now runs only after the response and fills missing ticker or bilingual company-name fields without replacing model-supplied data.
- Added model-reported recommendation timing badges for explicit dates, T+1, next-session, and tomorrow signals.
- Added entry, TP1, TP2, and stop-loss levels to compact client inquiry cards.

## v0.1.65
- Fixed client-inquiry classification so it is tied to the exact marked Telegram message instead of the whole source/channel.
- Prevented normal dated recommendation tables, charts, photos, and signals from being moved into the client-inquiry output.

## v0.1.64
- Lists every Qwen model exposed to the account that supports text-and-image analysis, with the most capable available Qwen vision model selected first.
- Uses `qwen3-vl-plus` as the default model for new Qwen configurations.
- Removed generated PDF reports and raw-response PDFs to reduce the time spent after analysis; HTML, Markdown, in-app tables, raw AI text, and local traces remain available.

## v0.1.63
- Fixed desktop release version synchronization: the Tauri bundle, Node package, Rust package, Python package, and API now share one release version.
- GitHub Actions now rejects tags that do not match every bundled version, preventing an installed build from repeatedly offering its own release as an update.
- Added a locally cached EGX stock catalog that maps codes to Arabic and English company names, learns confirmed aliases, and refreshes weekly.
- Reworked Results into one expandable row per analysis run, with nested recommendations and compact client-inquiry sections. Client message evidence is no longer displayed.

## v0.1.61
- Reduced analysis payload overhead by reusing exact duplicate content and optimizing only oversized images before they are sent to the AI provider.
- Added local, secret-free analysis timing diagnostics and clearer in-app analysis progress feedback.

## v0.1.60
- Restored the proven GitHub release path by removing the updater signing preflight that blocked builds before the existing signing process could run.

## v0.1.59
- Fixed Windows GitHub Actions updater signing verification by invoking the installed Tauri CLI directly instead of resolving it through `npx`.

## v0.1.58
- Added target-date analysis: retain the default next-day workflow or choose a historical target date.
- Historical analysis reads content from the prior Cairo day at 00:00 through 23:59 on the selected date, then keeps only recommendations explicitly intended for that selected date.

## v0.1.57
- Added selection controls for text, images, and audio transcripts; each saved analysis now records the exact inputs sent to the model.
- Improved next-day EGX recommendation filtering, source-level Results tables, fuzzy stock lookup, deletion of saved result artifacts, and Telegram session UX.
- Added a separate client-inquiry response section for `ردًا على استفسارات عملائنا`-style replies so they remain available without appearing as actionable recommendations.
- Removed stale dashboard analytics, moved manual Telegram collection into Settings, and added loading states and clearer request feedback.
- Hardened desktop update signing: local release scripts retain compatibility with the original signing key and GitHub Actions verifies the signing key before publishing an update.

## v0.1.56
- Analyze selected chats from yesterday at Cairo midnight through the current moment, then retain recommendations intended for the next trading day based on dates in text, images, and audio.
- Added saved, expandable analysis-result rows in Results; each generated result opens its full EGX recommendation table.
- Replaced the automatic analysis-complete toast with an OK-required completion popup.

## v0.1.55
- Added a persistent in-app EGX table grouped by stock code and name with one current row per source.
- Show entry, TP1, TP2, stop loss, support, resistance, expected return, risk, dates, status, and Arabic analysis in the app and exports.
- Preserve the latest non-empty levels from repeated source posts while retaining all source dates for traceability.

## v0.1.53
- Removed the invalid sidecar flattening step so PyInstaller can load `python312.dll` from its required `_internal` directory.

## v0.1.52
- Restored PyInstaller's supported _internal sidecar layout and package the complete sidecar directory.
- Added a pre-package check for sidecar\_internal\python312.dll to stop broken installers from being produced.
- Added the sidecar runtime directory to the child process DLL search path.
- Aligned desktop and Python version metadata for a fresh release tag.
## v0.1.51
- Restored PyInstaller's supported `_internal` sidecar layout and package the complete sidecar directory.
- Added a pre-package check for `sidecar\\_internal\\python312.dll` to stop broken installers from being produced.
- Added the sidecar runtime directory to the child process DLL search path.
- Aligned desktop and Python version metadata.

## v0.1.50
- Fixed python312.dll load failure â€” set `contents_directory='.'` in PyInstaller spec so all runtime files are placed flat in sidecar/ instead of inside `_internal/`

## v0.1.49
- Fixed python312.dll load failure â€” removed nonexistent `_internal` path from sidecar PATH injection, DLL files are flat in sidecar/

## v0.1.48
- Renamed installer artifacts from `egx-intelligence-*` to `egx-analyzer-*`
- Updated release workflow and build scripts to use new naming
- Renamed signing key file to `egx-analyzer.key`

## v0.1.47
- Renamed app from EGX Intelligence to EGX Analyzer across all UI, config, and build files

## v0.1.46
- Fixed stale data showing briefly when navigating between Results/Recommendations and Reports pages
- Fixed NaN% rendering in Recommendations table when confidence value is missing
- Moved signal color maps to module-level constants, removing duplicate definitions in Dashboard and Recommendations
- Removed no-op dead code line in structlog file processor

## v0.1.45
- Bundled vcruntime140.dll and vcruntime140_1.dll in PyInstaller sidecar to fix load failure on machines without VC++ redistributable

## v0.1.44
- Removed invalid NSIS installer config fields that caused build failure

## v0.1.43
- Fixed python312.dll load failure by prepending sidecar directory to PATH before spawning
- Merged Recommendations and Search into a single Results page with tab bar
- Moved Check Telegram button into page header
- Added BUY/SELL/HOLD color badges to Dashboard consensus table
- Split Channels page into Add and Analyze sections
- Replaced bare lookback slider with labeled card control
- Collapsed Settings into 4 accordion sections
- Added pulsing online indicator and sidebar active item accent border
- Unminified and reorganized styles.css

## v0.1.41
- Added persistent error log file at AppData/Local/EGX Intelligence/logs/app-errors.jsonl via structlog file sink
