# Desktop app

The desktop app is the same app in its own window, with a built-in local database (SQLite), so it needs no Docker, Postgres, or browser tab.

## Run it from source

    pip install -r requirements-desktop.txt
    python brandops_desktop.py

Add `--demo` to start with sample data, or `--browser` to use your web browser instead of a native window. Inside the app, the header has a "Try demo data" button.

## Where your data lives

One folder per user (Windows `%APPDATA%\BrandOps`, macOS `~/Library/Application Support/BrandOps`, Linux `~/.local/share/BrandOps`):

- `config/` your brands, categories, thresholds, and connector settings (copied from the defaults on first run, never overwritten by updates)
- `data_inbox/` where you drop exported files
- `brandops.db` the local database

To back up or move everything, copy that folder. Data status has an "Open data folder" button.

## Importing data

Open Data status, drop exports into the folders shown, and click Import now for each source. The import window sets how far back to load. Re-importing is safe: rows are updated, not duplicated.

## Build installers

Push the repo to GitHub, open Actions, choose build-desktop, and click Run workflow. When it finishes, download the Windows and macOS zips from the run's artifacts. To build on your own machine: `pip install -r requirements-desktop.txt` then `pyinstaller brandops.spec --noconfirm`.

## Limits

- The builds are unsigned, so Windows SmartScreen and macOS Gatekeeper will warn the first time (Windows: More info, Run anyway; macOS: right-click the app, Open).
- The GitHub macOS build matches the runner's chip (Apple Silicon); Intel Macs need their own build.
- The desktop build uses SQLite only and leaves out the GA4 API connector. For Postgres or GA4, run the server version.
- Linux: run from source. A native window needs GTK or Qt installed; otherwise the app opens in your browser.
