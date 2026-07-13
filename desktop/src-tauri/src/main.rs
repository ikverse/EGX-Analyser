#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{env, fs, path::PathBuf, process::Child, sync::Mutex};
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

enum EngineChild {
    Bundled(CommandChild),
    Patched(Child),
}

struct LocalEngine(Mutex<Option<EngineChild>>);

#[tauri::command]
fn restart_app(app: tauri::AppHandle) {
    stop_local_engine(&app);
    app.restart();
}

#[cfg(windows)]
fn terminate_orphaned_engines() {
    for image_name in ["egx-intelligence-api.exe", "egx-intelligence-api-x86_64-pc-windows-msvc.exe"] {
        let _ = std::process::Command::new("taskkill")
            .args(["/IM", image_name, "/T", "/F"])
            .creation_flags(0x0800_0000)
            .status();
    }
}

fn stop_local_engine(app: &tauri::AppHandle) {
    let engine = app.state::<LocalEngine>();
    let child = {
        let mut guard = engine.0.lock().expect("engine lock poisoned");
        guard.take()
    };
    if let Some(child) = child {
        let process_id = match &child {
            EngineChild::Bundled(process) => process.pid(),
            EngineChild::Patched(process) => process.id(),
        };
        #[cfg(windows)]
        {
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &process_id.to_string(), "/T", "/F"])
                .creation_flags(0x0800_0000)
                .status();
        }
        match child {
            EngineChild::Bundled(process) => { let _ = process.kill(); }
            EngineChild::Patched(mut process) => { let _ = process.kill(); }
        }
    }
    #[cfg(windows)]
    terminate_orphaned_engines();
}

fn engine_update_root() -> PathBuf {
    PathBuf::from(env::var_os("LOCALAPPDATA").unwrap_or_else(|| env::temp_dir().into_os_string()))
        .join("EGX Intelligence")
        .join("engine-updates")
}

fn promote_pending_engine() {
    let root = engine_update_root();
    let pending = root.join("pending");
    if !pending.join("egx-intelligence-api.exe").is_file() {
        return;
    }
    let current = root.join("current");
    let previous = root.join("previous");
    let _ = fs::remove_dir_all(&previous);
    if current.exists() {
        let _ = fs::rename(&current, &previous);
    }
    let _ = fs::rename(&pending, &current);
}

fn start_local_engine(app: &tauri::App) -> Result<EngineChild, Box<dyn std::error::Error>> {
    promote_pending_engine();
    let patched_engine = engine_update_root().join("current").join("egx-intelligence-api.exe");
    if patched_engine.is_file() {
        let child = std::process::Command::new(&patched_engine)
            .creation_flags(0x0800_0000)
            .spawn()
            ?;
        return Ok(EngineChild::Patched(child));
    }
    let (_events, child) = app.shell().sidecar("egx-intelligence-api")?.spawn()?;
    Ok(EngineChild::Bundled(child))
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
        .expect("error while building EGX Intelligence");

    app.run(|app, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            stop_local_engine(app);
        }
    });
}
