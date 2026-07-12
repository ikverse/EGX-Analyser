# Desktop updates

EGX Intelligence uses Tauri's signed updater. The application checks a public GitHub Release manifest at startup and from **Settings → Check for updates**. If a newer signed installer exists, the user can download it, install it, and restart without losing Telegram authorization, settings, API keys, channels, or the local database.

The normal NSIS installer automatically downloads Microsoft WebView2 if Windows does not already include it. Python, Node.js, Rust, Docker, and PostgreSQL are never installed on an end-user machine: the Python API is bundled as the app's sidecar.

## One-time publisher setup

1. Create a GitHub repository for EGX Intelligence. The project source may be private, but GitHub Release assets and `latest.json` must be publicly downloadable for the free update route.
2. Run the following once in PowerShell from the project folder, replacing the repository value:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\enable-updater.ps1 -Repository "YOUR_GITHUB_NAME/YOUR_REPOSITORY"
   ```

3. Back up the private signing key shown by the command. It is stored outside the project by default at `%USERPROFILE%\.tauri\egx-intelligence.key` and must never be committed, emailed, or shared. Losing this key prevents future updates to installed copies.
4. Commit the changed `desktop/src-tauri/tauri.conf.json`. It contains only the safe public key and public update URL.
5. In GitHub repository **Settings → Secrets and variables → Actions**, add:
   - `TAURI_SIGNING_PRIVATE_KEY`: the complete contents of the private key file.
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: the password used when creating the key; use an empty value only if no password was set.

## Publish an update

Update all three version fields to the same semantic version:

- `desktop/package.json`
- `desktop/src-tauri/Cargo.toml`
- `desktop/src-tauri/tauri.conf.json`

Commit those changes, then create and push a matching Git tag, for example `v0.1.1`. GitHub Actions builds the bundled backend, creates the signed installer and signature, generates `latest.json`, and publishes all of them to the release. Existing installations discover the release automatically.

For a local release build instead of GitHub Actions:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Repository "YOUR_GITHUB_NAME/YOUR_REPOSITORY" -Version "0.1.1" -ReleaseNotes "Short description of this version"
```

Upload the generated NSIS `.exe`, its `.exe.sig`, and `release/latest.json` to a GitHub Release tagged `v0.1.1`.

## Security and recovery

- The updater rejects unsigned or incorrectly signed installers.
- The public key is embedded in the desktop application; only installers signed by the matching private key can update it.
- The updater requires HTTPS in release builds.
- If a check fails, the user sees a short warning or error notification and can continue using the current installed version.
- Test every release on a non-production Windows account before publishing it broadly.
