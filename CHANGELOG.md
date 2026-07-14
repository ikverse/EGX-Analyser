# Changelog

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
