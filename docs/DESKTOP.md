# Windows desktop application

The installed application is a Tauri window containing the React dashboard. On startup it launches a bundled FastAPI executable bound only to `127.0.0.1:8000`; it stores data under `%LOCALAPPDATA%\EGX Intelligence`. Users therefore do not need Docker, PostgreSQL, Redis, Python, Node, or a browser after installation.

The installer does not package secrets. Configure the OpenAI and Telegram credentials from the app's **Settings** page; they are stored only in `%LOCALAPPDATA%\EGX Intelligence\.env`. The installer automatically installs Microsoft WebView2 when Windows does not already provide it.

## Create the installer

1. Run `scripts/bootstrap-windows.ps1 -DesktopBuild -SkipDocker` to create `.venv`, and install Python, Node.js, and Rust. These are build-only prerequisites.
2. Ensure the Microsoft C++ Build Tools are installed for the Rust MSVC toolchain.
3. Run `scripts/build-desktop.ps1`.
4. Distribute the generated NSIS `.exe` from `desktop/src-tauri/target/release/bundle/nsis/`.

The build script packages `desktop/sidecar_server.py` with PyInstaller and gives it the Windows target suffix required by Tauri. Tauri embeds that executable as a sidecar and starts it when the desktop app opens. Before public distribution, code-sign both the installer and sidecar, define a release-update endpoint, and move authentication to an identity provider.

## Automatic updates

For signed in-app updates using free GitHub Releases, follow `docs/UPDATES.md`. The updater is intentionally not active until its one-time signing-key and GitHub repository setup is complete.
