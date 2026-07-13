#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct LocalEngine(Mutex<Option<CommandChild>>);

#[tauri::command]
fn restart_app(app: tauri::AppHandle) {
    app.restart();
}

fn stop_local_engine(app: &tauri::AppHandle) {
    let engine = app.state::<LocalEngine>();
    let child = {
        let mut guard = engine.0.lock().expect("engine lock poisoned");
        guard.take()
    };
    if let Some(child) = child {
        let _ = child.kill();
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![restart_app])
        .setup(|app| {
            let (_events, child) = app.shell().sidecar("egx-intelligence-api")?.spawn()?;
            app.manage(LocalEngine(Mutex::new(Some(child))));
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
