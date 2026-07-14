#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Child;
use std::sync::Mutex;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Manager, RunEvent, WindowEvent};

// Wraps the spawned sidecar process. Using std::process::Child instead of
// tauri_plugin_shell::CommandChild so we can launch the --onedir executable
// directly from the resource directory without the externalBin mechanism
// (which requires a single-file exe and triggers the Windows Defender ASR
// "Block executable files from running" rule via %TEMP% self-extraction).
struct LocalEngine(Mutex<Option<Child>>);

#[tauri::command]
fn restart_app(app: tauri::AppHandle) {
    stop_local_engine(&app);
    app.restart();
}

#[cfg(windows)]
fn terminate_orphaned_engines() {
    let _ = std::process::Command::new("taskkill")
        .args(["/IM", "egx-intelligence-api.exe", "/T", "/F"])
        .creation_flags(0x0800_0000)
        .status();
}

fn stop_local_engine(app: &tauri::AppHandle) {
    let engine = app.state::<LocalEngine>();
    let child = {
        let mut guard = engine.0.lock().expect("engine lock poisoned");
        guard.take()
    };
    if let Some(mut child) = child {
        let pid = child.id();
        #[cfg(windows)]
        {
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(0x0800_0000)
                .status();
        }
        let _ = child.kill();
    }
    #[cfg(windows)]
    terminate_orphaned_engines();
}

fn start_local_engine(app: &tauri::App) -> Result<Child, Box<dyn std::error::Error>> {
    #[cfg(windows)]
    terminate_orphaned_engines();

    // Resolve the sidecar folder from the Tauri resource directory.
    // build-desktop.ps1 copies dist/egx-intelligence-api/ → src-tauri/sidecar/
    // and tauri.conf.json bundles it as resources: { "sidecar/**/*": "sidecar/" }
    let resource_dir = app.path().resource_dir()?;
    let exe = resource_dir
        .join("sidecar")
        .join("egx-intelligence-api.exe");

    let sidecar_dir = exe.parent().unwrap_or(&resource_dir);

    // Prepend sidecar dir to PATH so Windows resolves python312.dll and
    // VC++ runtime deps from the flat onedir layout without a system-wide install.
    let new_path = match std::env::var("PATH") {
        Ok(existing) => format!("{};{}", sidecar_dir.display(), existing),
        Err(_) => sidecar_dir.display().to_string(),
    };

    let mut cmd = std::process::Command::new(&exe);
    cmd.current_dir(sidecar_dir);
    cmd.env("PATH", new_path);
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    let child = cmd.spawn()?;

    Ok(child)
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![restart_app])
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                stop_local_engine(&window.app_handle());
            }
        })
        .setup(|app| {
            app.manage(LocalEngine(Mutex::new(Some(start_local_engine(app)?))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building EGX Analyzer");

    app.run(|app, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            stop_local_engine(app);
        }
    });
}
