# Changelog

## v0.1.121
- Redesigned Results history with compact rows, target-date grouping, source and result filters, a latest-run indicator, clear empty-result states, and less prominent destructive actions.
- Opened recommendation details immediately from each clickable, keyboard-accessible result row, kept only one run expanded, and hid empty inquiry sections and duplicated run summaries.
- Preserved selected Telegram channel names for empty analyses so Results remains traceable even when the model returns no recommendations.
- Simplified the recommendation table to 15 columns by moving Source image after Timing and removing the visible Type column while preserving recommendation-type data internally.
- Improved recommendation readability with tighter rows, sticky context, compact image controls, green Entry values, cyan targets, red stops, percentage suffixes, and clearer price-group separators.
- Made every Settings section collapsed by default and turned the AI, Telegram, Catalog, and App summary cards into accessible shortcuts that expand, focus, and scroll to the corresponding section.
- Added regression coverage for the revised table geometry, compact result behavior, Settings navigation, percentage rendering, and empty-result source preservation.

## v0.1.120
- Recognized `أهم الأسهم اليوم` as explicit recommendation context and extracted every stock row in its following table while preserving the general important-stock exclusion elsewhere.
- Merged complementary panels for the same stock and Telegram image into one source row without losing Watching, entry, TP1, TP2, return, stop, or evidence details.
- Corrected the trusted ASCM identity and made catalog enrichment fall back safely to source-provided names if the local catalog is unavailable or untrusted.
- Aligned displayed Buy, Sell, and Hold signals with explicit model recommendation types.
- Reworked automatic and historical analysis windows around exact Cairo calendar boundaries, preserved selected weekend dates, and corrected the inclusive source-date label sent to the model.
- Prevented background Telegram refreshes from invoking AI, restricted the app to one concurrent model analysis, and retained unsupported voice notes as pending rather than marking them processed.
- Added accurate analyzed-input counts, paginated Results history, bounded startup retries, retry controls, and complete Qwen endpoint round-tripping in Settings.
- Removed obsolete PDF, Streamlit, scheduler, Docker, and unused legacy interface paths while keeping existing saved Results compatible.
- Added regression coverage, refreshed the architecture and user documentation, and made backend lint, backend tests, and the frontend build mandatory in the release workflow.

## v0.1.119
- Rebuilt consolidated analysis around one canonical, versioned prompt with a strict same-source date gate and concise runtime context.
- Prevented incompatible downloaded content-pack prompts from silently overriding the bundled prompt, while recording the selected prompt source and schema in each provider trace.
- Clarified news exclusion, destination separation, Watching rules, source traceability, price extraction, TP1/TP2 handling, and concise Arabic Notes in one maintainable contract.
- Removed the model-owned Status field and derived internal Buy, Sell, or Hold signals deterministically from accepted recommendation rows.
- Removed Status from Results, Markdown reports, and HTML reports while keeping legacy saved results readable.
- Retained the lightweight local explicit-date safety guard so mismatched ordinary recommendations are excluded without another model request.
- Added regression coverage for prompt compatibility, prompt trace metadata, deterministic signals, strict date wording, and the revised 16-column Results layout.

## v0.1.118
- Removed the T+1 timing category, prior-date exception, runtime validator, saved-result filtering, Notes synthesis, and legacy UI mappings.
- Limited recommendation timing to an exact target date or an explicit Watching context.
- Added a highest-priority model exclusion for news and urgent-news content across images, text messages, and voice-note transcripts, including Arabic and English equivalents.
- Prevented custom Include phrases from overriding the news exclusion and kept excluded content out of all result categories and source links.
- Fixed Results-table header and value alignment with a fixed 17-column layout, dedicated numeric alignment, and a wider Entry column for price ranges.
- Added regression coverage for the revised prompt rules and range-safe Results-table geometry.

## v0.1.117
- Redesigned application messages as a responsive toast stack with distinct success, warning, and error states, manual dismissal, timeout progress, pause-on-hover or focus, and reduced-motion support.
- Required a literal `T+1` or `t+1` token in same-stock `timing_evidence` before accepting any T+1 recommendation.
- Prevented generated Notes, summaries, translations, paraphrases, and inferred next-day wording from qualifying as T+1 evidence.
- Hid unsupported T+1 rows from existing saved results and reported concise warnings containing the affected stock code and Telegram message ID.
- Required the model output contract to include visible source date, date evidence, and timing evidence fields on every recommendation data point.
- Added regression coverage for unsupported and valid T+1 evidence while preserving Watching and explicit-date recommendations.

## v0.1.116
- Taught the analysis model to extract TP1 and TP2 from `منطقة البيع`, `نطاق البيع`, and equivalent exit-zone wording without changing a Buy recommendation to Sell.
- Added separate TP1 Return % and TP2 Return % fields beside their corresponding targets in Results.
- Preserved explicit `عائد الربح` percentages and calculated missing returns from available entry and target values.
- Used the upper bound of an entry range for return calculations and applied direction-aware formulas to Buy and Sell recommendations.
- Backfilled compatible saved results and updated Markdown and HTML report exports with the new per-target return columns.

## v0.1.115
- Rebuilt client inquiry replies as a responsive two-column card grid that becomes one column on narrower layouts.
- Limited single-reply cards to a readable width and allowed cards of different lengths to keep their natural height.
- Improved bidirectional alignment for Arabic company names, English names, and ticker symbols.
- Standardized card headers, trend badges, text sections, market levels, spacing, wrapping, and mobile behavior.
- Hid unavailable entry-price fields instead of displaying empty placeholder values.

## v0.1.114
- Added a `Watching` Timing category for explicit same-stock watch recommendations found in images, text messages, and voice-note transcripts.
- Recognized equivalent Arabic and English watch wording while preserving entry or breakout conditions, TP1, TP2, stop loss, returns, risks, source dates, and concise Arabic Notes.
- Restricted T+1 classification to the exact contiguous literal `T+1` or `t+1`, rejecting translations, synonyms, spaced variants, and date-based inference.
- Kept existing saved results compatible with common legacy Watching timing values without changing explicit-date behavior.
- Realigned the Configure and Analyze model controls, action button, and running-progress status across desktop and narrow layouts.

## v0.1.113
- Added a Target Date column to every Results recommendation row while keeping the source date separately visible.
- Made the shorter, fitted Results-table layout permanent and removed the Compact view control and its conditional styling.
- Rendered Settings information popups in a document-level overlay so later cards and accordion sections cannot cover them.
- Improved popup placement using its actual size and available viewport space while preserving dismissal and focus behavior.
- Kept older saved results compatible by showing an unavailable Target Date as a dash.

## v0.1.112
- Replaced fragile model-returned source labels with trusted local channel resolution based on Telegram message IDs.
- Removed redundant provenance, evidence, duplicate-value, and inquiry-classification validation along with the second Qwen correction request.
- Kept each analysis to one model request, excluding only results with missing or unknown Telegram message IDs.
- Removed emojis from channel names shown to the model, Results, reports, APIs, and traces without changing stored Telegram data.
- Bound recommendation images locally by Telegram message ID, with safe handling for messages containing multiple images.

## v0.1.111
- Made each Settings section expand or collapse from anywhere across its header while keeping information icons independent.
- Added native keyboard operation and clear focus feedback to every Settings accordion header.
- Smoothed collapsed and expanded section edges with consistent rounded clipping, hover treatment, and chevron alignment.

## v0.1.110
- Left-aligned collapsed Settings titles and statuses and placed each information icon directly beside its heading.
- Standardized information controls and replaced text arrows with consistently aligned SVG chevrons.
- Added explicit form-row placement to prevent conditional fields from moving unpredictably or stretching to textarea height.
- Aligned provider credentials, endpoints, Include/Exclude phrases, preview headings, overview values, and the sticky save action across desktop and narrow layouts.

## v0.1.109
- Explicitly classified `يسمح بالتداول على سعر الشراء المحدد` as entry-price execution tolerance rather than T+1 or next-session timing.
- Applied the same exclusion to percentage-deviation wording around a specified entry price.
- Prevented that wording from being returned as `timing_evidence` or moving a visibly dated recommendation to the following day.
- Repeated the rule across the base prompt, date contract, target-date instructions, and final model self-audit with regression coverage.

## v0.1.108
- Replaced persistent Settings explanations with compact information popups beside section headings and individual controls.
- Added accessible popup behavior with one-open-at-a-time state, outside-click and Escape dismissal, focus return, and responsive viewport positioning.
- Kept live warnings, errors, connection states, catalog status, and diagnostic results directly visible while reducing static page clutter.
- Styled the cleaner Settings layout and contextual help consistently across dark and light themes.

## v0.1.107
- Required the model to distinguish explicit-date recommendations from T+1 recommendations using visible source dates and exact contextual evidence.
- Accepted clear Arabic and English next-session equivalents only when they belong to the same stock recommendation, without inferring T+1 from a previous-day date alone.
- Added a mandatory model date-eligibility self-audit that excludes unsupported rows before ranking, categorization, mention counting, and Notes generation.
- Preserved visible source dates, date evidence, and timing evidence with saved result rows while keeping semantic analysis in the configured model.

## v0.1.106
- Interleaved every analysis image directly with its source, timestamp, Telegram message ID, and immutable image reference in Qwen and compatible multimodal requests.
- Added exact image-reference traceability so model-returned recommendation rows bind to trusted local source metadata instead of shifted or fabricated message IDs.
- Prevented new results without a valid image reference from falling back to an unrelated message image while preserving legacy saved-result compatibility.
- Added regression coverage for interleaved provider content, shifted source correction, exact image linking, and safe missing-reference behavior.

## v0.1.105
- Replaced Supplementary extraction guidance with permanent Include and Exclude phrase controls that extend the unchanged base analysis prompt.
- Added phrase normalization, exclusion priority, conflict warnings, unsaved-change feedback, active counts, and an effective prompt-section preview.
- Added a permanent Cairo-timestamped phrase history with reset, historical restore, recent-entry loading, and damaged-file backup recovery.
- Removed legacy supplementary guidance while preserving provider credentials, stock/date/source rules, TP1/TP2 handling, and existing result behavior.
- Hid the redundant Local engine online label from the main header while retaining engine health checks and startup recovery.

## v0.1.104
- Loaded authorized Telegram chats automatically once per app session and changed the manual action to Refresh Telegram chats.
- Removed the repeated Stock column from recommendation rows, made Source the first column, and kept it visible during horizontal scrolling while stock identity remains in each colored group row.
- Trusted the model prompt for recommendation meaning by removing local evidence-identity, recommendation-wording, and non-actionable-content rejection checks.
- Retained message/source provenance, evidence presence, duplicate-value safeguards, and client-inquiry consistency checks with regression coverage.

## v0.1.103
- Removed the Results history overview box, aggregate counters, and shortcut controls so the Results tab opens directly on its saved-run table.
- Stabilized the Actions column with equal-size View/Hide and Delete controls, centered icons and labels, and non-wrapping button text.

## v0.1.102
- Preserved distinct stock recommendations that use the same visual template by sending every non-identical image to the model for stock-aware review.
- Kept exact byte-for-byte repost consolidation while tracking visually similar images without discarding their ticker, date, or trade values.
- Moved horizontal stock identity visibility to each colored stock-group row and allowed the regular Stock column to scroll with the table.
- Replaced the basic engine-wait screen with a responsive branded startup experience and clearer local-service status.
- Added the sole Light/Dark switch to the bottom of the expanded navigation and removed the redundant Appearance box from Settings.

## v0.1.101
- Simplified Results into a five-column run history with a compact findings overview while retaining runtime diagnostics internally.
- Added a compact-by-default, collapsible navigation sidebar that gives recommendation tables more horizontal space and remembers the selected layout.
- Aligned the Analysis model selector and action controls in Configure and analyze.
- Added end-to-end cancellation for long-running analyses from both the page header and analysis action area, including active Qwen and Ollama requests.
- Fixed structured logging failures so empty analysis windows return the intended explanation instead of crashing and background content-update events remain traceable.

## v0.1.100
- Generated concise Arabic stock Notes across new and compatible saved results while retaining ticker codes, numbers, T+1, distinct trade levels, and separate source traceability.
- Added a sticky Stock column with ticker and English/Arabic company names so stock identity remains visible while scrolling through Results.
- Required exact stock-specific recommendation evidence and excluded liquidity, sector, support/resistance, completed-trade, and other non-recommendation context from active results.
- Added duplicate-image, repeated-value, and cross-stock contamination checks, including visually equivalent recompressed repost detection.
- Added one focused Qwen correction pass for invalid provenance and prevented unresolved misleading model output from being saved.

## v0.1.99
- Fixed analysis failures on existing desktop installations whose SQLite database predates recommendation entry-range columns.
- Added automatic startup migration for nullable `entry_low` and `entry_high` fields while preserving existing recommendation data.
- Added regression coverage that upgrades a legacy database and verifies its saved recommendation values remain intact.

## v0.1.98
- Corrected saved result timestamps so UTC database values display with the proper Cairo time and daylight-saving offset.
- Renamed each generated result to `Analysis Recommendations` with its target date.
- Added separate Generated at and Sources columns to the Results history table.
- Consolidated unique recommendation and inquiry sources in the main result row while retaining detailed source references inside expanded results.

## v0.1.97
- Consolidated Results Notes into one concise, stock-specific summary across all occurrences while preserving source rows and references separately.
- Merged equivalent Arabic and English recommendation wording without repeating the same insight, while retaining distinct T+1, watchlist, entry, target, stop-loss, and risk information.
- Limited recommendation extraction and display to TP1 and TP2, excluding TP3 and later targets in Arabic and English even when returned by the model.
- Added backward-compatible Notes generation for existing saved results without requiring a database migration.
- Added the release version and changelog summary to GitHub Actions runs, GitHub Releases, and the in-app update manifest.

## v0.1.96
- Refined Channels with denser rows, clearer checkbox selection, and a sticky analysis action area.
- Added live analysis phase and elapsed-time feedback in the application header.
- Improved the recommendation table with sticky headers and source column, a compact-row toggle, and scroll guidance.
- Reorganized AI settings into a responsive two-column layout with a compact, reachable save action.

## v0.1.95
- Combined each expanded analysis run's metadata and timing into one responsive summary card.

## v0.1.94
- Fixed the release build timing formatter so GitHub Actions continues from PyInstaller packaging into Rust and Tauri packaging.

## v0.1.93
- Fixed result-table source images in packaged Windows builds by allowing Tauri's asset protocol to read the managed local Telegram image folder.

## v0.1.92
- Preserved Rust compilation caches across application version-only releases instead of invalidating them with Node or Python metadata.
- Added prefix-restored npm and pip download caches so dependency archives survive release-version changes.
- Added release-log timings for Python sidecar packaging, Rust preflight, Tauri packaging, and total build time.

## v0.1.91
- Stops the local `egx-intelligence-api` sidecar before the Windows updater applies an installer.
- Restores the local engine automatically if downloading or installing an update fails.

## v0.1.90
- Rebuilt Light and Dark mode around a centralized charcoal-and-teal token system with stronger accessible contrast.
- Removed gradients and elevated shadow styling in favor of flat, bordered surfaces, consistent controls, and semantic status colors.
- Stabilized recommendation-table column widths so dates, prices, badges, and actions remain readable without vertical wrapping.
- Applied the saved theme before React starts to prevent an incorrect-theme flash during launch.

## v0.1.89
- Replaced the violet theme with a centralized blue-slate Light and Dark palette.
- Improved contrast for surfaces, borders, text, selected states, and semantic status feedback.
- Replaced gradient primary buttons with solid accessible blue interaction states.

## v0.1.88
- Refined Channels into a clearer select-then-analyze workspace with stronger selected states and responsive controls.
- Stabilized Results history columns and actions while preserving the full recommendation-table behavior.
- Improved Settings grouping, status summaries, and responsive layout for faster scanning.

## v0.1.87
- Rotated the Tauri updater public key after verifying the new `egx-analyzer-2026` signing-key pair.
- Requires one manual installer download from GitHub Releases to migrate existing installations; later in-app updates use the new signing identity.

## v0.1.86
- Accelerated GitHub release builds with npm, pip, and Rust/Cargo dependency caches.
- Made CI dependency installation deterministic and removed redundant installation work during the signed desktop build.
- Serialized releases for the same tag and fail-fast when expected release files are missing.

## v0.1.85
- Strengthened the centralized Light and Dark theme contrast across navigation, cards, tables, inputs, selected rows, and status states.
- Replaced the packaged Windows taskbar icon with the current EGX Analyzer mark and explicitly configured it for desktop bundles.

## v0.1.84
- Fixed the packaged desktop app becoming stuck on its startup screen by allowing its WebView to connect to the local loopback intelligence engine.

## v0.1.83
- Replaced all application table-header gradients with solid Light/Dark theme surfaces.
- Added direct analysis-completion navigation to the newly created Result, including automatic expansion, scroll, and visual focus.
- Added Results shortcuts for opening the latest run and returning to Channels.
- Moved model-output audit notices from Results to Settings diagnostics.
- Standardized displayed timestamps, reports, diagnostics, analysis traces, and saved media folders on the DST-aware Africa/Cairo timezone.

## v0.1.82
- Removed local correction and mutation of AI analysis output; the model response is now saved exactly as returned, with validation warnings retained for traceability.
- Enabled Tauri's asset protocol feature required by saved Telegram source-image previews in packaged builds.
- Refined the shared Light and Dark themes with a light-responsive sidebar, stronger text contrast, darker dark-mode surfaces, and flat token-driven component styling without shadows or glows.

## v0.1.81
- Replaced the desktop application icon with the EGX Analyzer violet market-and-pyramid mark and added the same icon beside the app name on startup and in navigation.
- Enabled Tauri asset-protocol access for saved Telegram source images so source-image previews can load inside the app.

## v0.1.80
- Rebuilt the application visual system around a lavender, violet, indigo, and blush palette.
- Added centralized Light and Dark design tokens for reusable colors, surfaces, typography, borders, shadows, and component states.
- Added a persistent Settings appearance switcher and updated navigation, forms, tables, dialogs, results, and cards to adapt to both themes.

## v0.1.79
- Added a source-image button to each recommendation row when its saved Telegram image can be matched by channel and source message ID.
- Added an in-app image viewer with multi-image navigation and direct file access.
- Makes matching source images available to both new and previously saved Results entries.

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
