# termnotes

Notes displayed directly in a sidebar in your terminal – attached via a dedicated `tmux` session with a persistent daemon.

## Features

- Notes are shown as a right-hand sidebar in a dedicated `tmux` session
- A daemon keeps the session and panel alive automatically (including after reboot)
- Automatic panel recovery: if the panel is closed, the daemon reopens it
- Panel size is saved on exit and restored on the next start
- Falls back to a `curses`-based TUI if `tmux` is not available
- Notes are stored as JSON under `~/.termnotes`

## Installation

Requirements: `python3` and `tmux`.

```bash
git clone <repo-url> termnotes
cd termnotes
sudo ./install.sh
```

The install script will:

- copy the program to `/usr/local/lib/termnotes` and symlink `termnotes` into `/usr/local/bin`
- create and enable the systemd service `termnotes`
- set up autostart for the detected login shell (bash, zsh, fish)

Without systemd or root access, termnotes can also run directly from the repository:

```bash
./termnotes
```

## Usage

| Command | Description |
| --- | --- |
| `termnotes` | Attach to the session (panel on the right) |
| `termnotes add name text` | Add a note |
| `termnotes rm name` | Delete a note |
| `termnotes list` | List all notes in the terminal |
| `termnotes setsize 40` | Set panel width in percent (10–80) |
| `termnotes daemon status` | Show daemon and session status |
| `termnotes daemon restart` | Restart the daemon |
| `termnotes daemon stop` | Stop daemon and session |

Example:

```bash
termnotes add todo Shopping: bread, milk, coffee
termnotes add ideas New TUI with categories
```

### Panel size

The panel size can be adjusted at runtime (`tmux resize-pane`) and is saved on exit. Alternatively, set it directly:

```bash
termnotes setsize 40
```

## Uninstall

```bash
sudo ./uninstall.sh
```

Your notes under `~/.termnotes` are kept.

## Data

All data lives under `~/.termnotes/`:

- `notes.json` – the notes
- `config.json` – settings (e.g. panel size)
- `daemon.pid` / `daemon.lock` – daemon runtime information
