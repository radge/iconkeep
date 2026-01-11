# iconkeep

A small CLI to back up and restore macOS application icons.

## Usage

```bash
uv sync --no-editable
uv run iconkeep backup "Safari"
uv run iconkeep restore "Safari"
```

You can also pass a path to a `.app` bundle instead of a name.

If you omit the app argument, iconkeep will read `~/.config/iconkeep/apps`
(or `$XDG_CONFIG_HOME/iconkeep/apps`). The file is one app per line; blank
lines and lines starting with `#` are ignored.

Backups are stored under `~/.local/share/iconkeep/backups/` (or `$XDG_DATA_HOME/iconkeep/backups/`).
Cache and state directories follow `$XDG_CACHE_HOME/iconkeep` and `$XDG_STATE_HOME/iconkeep` (currently unused).

Note: With Python 3.14, editable installs use hidden `.pth` files that are ignored by the interpreter. Use `uv sync --no-editable` to ensure the CLI entry point can import the package.
