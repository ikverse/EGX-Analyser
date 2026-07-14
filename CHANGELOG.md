# Changelog

## v0.1.51
- Fixed python312.dll load failure — PyInstaller 6+ places runtime files in `_internal/` by default which the bootloader hardcodes; build script now flattens `_internal/` into the sidecar root after PyInstaller builds so the exe finds all DLLs next to itself
- Removed ineffective `contents_directory='.'` from PyInstaller spec (PyInstaller 6 converts it to None internally, does not disable `_internal`)

## v0.1.50
- Fixed python312.dll load failure — set `contents_directory='.'` in PyInstaller spec so all runtime files are placed flat in sidecar/ instead of inside `_internal/`

## v0.1.49
- Fixed python312.dll load failure — removed nonexistent `_internal` path from sidecar PATH injection, DLL files are flat in sidecar/

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
