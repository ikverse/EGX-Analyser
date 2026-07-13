#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct LocalEngine(Mutex<Option<CommandChild>>);

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
        let process_id = child.pid();
        #[cfg(windows)]
        {
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &process_id.to_string(), "/T", "/F"])
                .creation_flags(0x0800_0000)
                .status();
        }
        let _ = child.kill();
    }
    #[cfg(windows)]
    terminate_orphaned_engines();
}

fn start_local_engine(app: &tauri::App) -> Result<CommandChild, Box<dyn std::error::Error>> {
    #[cfg(windows)]
    terminate_orphaned_engines();
    let (_events, child) = app.shell().sidecar("egx-intelligence-api")?.spawn()?;
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
        .expect("error while building EGX Intelligence");

    app.run(|app, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            stop_local_engine(app);
        }
    });
}
