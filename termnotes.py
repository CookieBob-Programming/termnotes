#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


DATA_DIR = Path.home() / ".termnotes"
DATA_FILE = DATA_DIR / "notes.json"
CONFIG_FILE = DATA_DIR / "config.json"
DAEMON_PID = DATA_DIR / "daemon.pid"
DAEMON_LOCK = DATA_DIR / "daemon.lock"
TMUX_LOCK = DATA_DIR / "tmux.lock"
SESSION = "termnotes"
REFRESH = 1.0
DEFAULT_PANEL_PCT = 30
MIN_PANEL_PCT = 10
MAX_PANEL_PCT = 80
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def script_path():
    return str(Path(__file__).resolve())


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(CONFIG_FILE)


def panel_pct():
    config = load_config()
    try:
        pct = int(config.get("panel_pct", DEFAULT_PANEL_PCT))
    except (TypeError, ValueError):
        pct = DEFAULT_PANEL_PCT
    return max(MIN_PANEL_PCT, min(MAX_PANEL_PCT, pct))


def load_notes():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_notes(notes):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(DATA_FILE)


def cmd_add(namespace):
    notes = load_notes()
    if namespace.name in notes:
        print(f"Note '{namespace.name}' existiert bereits.", file=sys.stderr)
        return 1
    notes[namespace.name] = " ".join(namespace.text)
    save_notes(notes)
    print(f"Note '{namespace.name}' hinzugefuegt.")
    return 0


def cmd_rm(namespace):
    notes = load_notes()
    if namespace.name not in notes:
        print(f"Note '{namespace.name}' nicht gefunden.", file=sys.stderr)
        return 1
    del notes[namespace.name]
    save_notes(notes)
    print(f"Note '{namespace.name}' geloescht.")
    return 0


def cmd_list(namespace):
    notes = load_notes()
    if not notes:
        print("Keine Notizen vorhanden.")
        return 0
    width = max(len(n) for n in notes)
    for name, text in notes.items():
        print(f"{name.ljust(width)}  {text}")
    return 0


def render_panel():
    notes = load_notes()
    width, height = shutil.get_terminal_size((80, 24))
    inner_w = max(10, width - 4)
    BOLD = "\x1b[1m"
    RESET = "\x1b[0m"
    lines = []
    lines.append("┌" + "─" * (inner_w - 2) + "┐")
    title_pad = inner_w - 2 - len("NOTES")
    left = max(0, title_pad // 2)
    lines.append("│" + " " * left + f"{BOLD}NOTES{RESET}" + " " * (title_pad - left) + "│")
    lines.append("├" + "─" * (inner_w - 2) + "┤")
    if not notes:
        lines.append("│" + "Keine Notizen".center(inner_w - 2) + "│")
    else:
        for name, text in sorted(notes.items()):
            for pline in render_note_lines(name, text, inner_w - 2):
                lines.append("│" + pad_visible(pline, inner_w - 2) + "│")
    max_content = height - 3
    if len(lines) > max_content + 3:
        lines = lines[: max_content + 3]
    while len(lines) < max(4, height - 1):
        lines.append("│" + " " * (inner_w - 2) + "│")
    lines.append("└" + "─" * (inner_w - 2) + "┘")
    return "\n".join(lines)


def wrap_words(words, width):
    lines = []
    cur = ""
    for w in words:
        while len(w) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(w[:width])
            w = w[width:]
        cand = (cur + " " + w) if cur else w
        if len(cand) <= width:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_note_lines(name, text, width):
    BOLD = "\x1b[1m"
    RESET = "\x1b[0m"
    prefix = f"{BOLD}{name}:{RESET} "
    prefix_w = len(name) + 2
    content = wrap_words(text.split(), width)
    if not content:
        return [prefix]
    lines = []
    first = content[0]
    if first and len(first) <= width - prefix_w:
        lines.append(prefix + first)
        rest = content[1:]
    else:
        lines.append(prefix)
        rest = content
    indent = " " * prefix_w
    for cl in rest:
        lines.append(indent + cl)
    return lines


def vis_len(s):
    return len(ANSI_RE.sub("", s))


def pad_visible(s, width):
    return s + " " * max(0, width - vis_len(s))


def cmd_panel(namespace):
    try:
        while True:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.write(render_panel())
            sys.stdout.flush()
            time.sleep(REFRESH)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    return 0


def is_session():
    return subprocess.run(
        ["tmux", "has-session", "-t", SESSION],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def acquire_lock(path):
    try:
        lock = open(path, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except OSError:
        return None


def panel_cmd():
    return f"{shlex.quote(sys.executable)} {shlex.quote(script_path())} panel"


def ensure_session():
    if is_session():
        return
    lock = acquire_lock(TMUX_LOCK)
    if lock is None:
        return
    try:
        if is_session():
            return
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", SESSION, "-c", str(Path.home())],
            check=True,
        )
        home = str(Path.home())
        subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "off"], check=True)
        subprocess.run(
            ["tmux", "split-window", "-h", "-p", str(panel_pct()), "-c", home, "-t", SESSION],
            check=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{SESSION}.1", panel_cmd(), "Enter"],
            check=True,
        )
        subprocess.run(["tmux", "select-pane", "-t", f"{SESSION}.0"], check=True)
    finally:
        lock.close()


def pane_has_panel(pid):
    try:
        out = subprocess.run(
            ["ps", "--ppid", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    for line in out.splitlines():
        if "termnotes.py" in line and re.search(r"\spanel\b", line):
            return True
    return False


def ensure_panel():
    if not is_session():
        return
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-t", SESSION, "-F", "#{pane_index} #{pane_pid} #{pane_current_command}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return
    panes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            panes[parts[0]] = (parts[1], parts[2])
    shells = {"bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh", "mksh"}
    lock = acquire_lock(TMUX_LOCK)
    if lock is None:
        return
    try:
        if "0" in panes:
            pid, cmd = panes["0"]
            if cmd not in shells and pid.isdigit() and pane_has_panel(pid):
                subprocess.run(
                    ["tmux", "send-keys", "-t", f"{SESSION}.0", "C-c"],
                    check=True,
                )
        if "1" not in panes:
            subprocess.run(["tmux", "split-window", "-h", "-p", str(panel_pct()), "-c", str(Path.home()), "-t", SESSION], check=True)
            subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}.1", panel_cmd(), "Enter"], check=True)
            subprocess.run(["tmux", "select-pane", "-t", f"{SESSION}.0"], check=True)
        elif panes["1"][1] in shells:
            subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}.1", panel_cmd(), "Enter"], check=True)
    finally:
        lock.close()


def daemon_running():
    if not DAEMON_PID.exists():
        return False
    try:
        pid = int(DAEMON_PID.read_text("utf-8").strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def persist_current_size():
    if not is_session():
        return
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-t", SESSION, "-F", "#{pane_index} #{pane_width}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return
    widths = {}
    for line in out.splitlines():
        parts = line.split()
        if parts:
            try:
                widths[parts[0]] = int(parts[1])
            except ValueError:
                pass
    if "0" not in widths or "1" not in widths:
        return
    total = widths["0"] + widths["1"]
    if total <= 0:
        return
    pct = max(MIN_PANEL_PCT, min(MAX_PANEL_PCT, round(widths["1"] * 100 / total)))
    config = load_config()
    if config.get("panel_pct") != pct:
        config["panel_pct"] = pct
        save_config(config)


def daemon_loop():
    ensure_session()
    while True:
        try:
            ensure_session()
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "off"])
            ensure_panel()
            persist_current_size()
        except (subprocess.CalledProcessError, OSError):
            pass
        time.sleep(5)


def daemon_main():
    os.chdir(str(Path.home()))
    lock = acquire_lock(DAEMON_LOCK)
    if lock is None:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DAEMON_PID.write_text(str(os.getpid()), "utf-8")
    try:
        daemon_loop()
    finally:
        try:
            if DAEMON_PID.exists() and DAEMON_PID.read_text("utf-8").strip() == str(os.getpid()):
                DAEMON_PID.unlink()
        except OSError:
            pass
        lock.close()


def start_daemon_process():
    if daemon_running():
        return False
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        return True
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    os.chdir(str(Path.home()))
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    daemon_main()
    os._exit(0)


def wait_for_session(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_session():
            return True
        time.sleep(0.5)
    return False


def cmd_setsize(namespace):
    pct = max(MIN_PANEL_PCT, min(MAX_PANEL_PCT, namespace.percent))
    config = load_config()
    config["panel_pct"] = pct
    save_config(config)
    if is_session():
        try:
            subprocess.run(
                ["tmux", "resize-pane", "-t", f"{SESSION}.1", "-x", f"{pct}%"],
                check=True,
            )
        except subprocess.CalledProcessError:
            print("Session aktiv, aber Panel konnte nicht angepasst werden.", file=sys.stderr)
            return 1
    print(f"Panel-Groesse auf {pct}% der Breite gesetzt.")
    return 0


def cmd_daemon_start(namespace):
    if daemon_running():
        print("Daemon laeuft bereits.")
        return 0
    if not shutil.which("tmux"):
        print("tmux wird benoetigt, aber ist nicht installiert.", file=sys.stderr)
        return 1
    start_daemon_process()
    wait_for_session()
    print("Daemon gestartet. Mit 'termnotes' anhaengen.")
    return 0


def cmd_daemon_stop(namespace):
    if daemon_running():
        try:
            pid = int(DAEMON_PID.read_text("utf-8").strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError):
            pass
    if is_session():
        subprocess.run(["tmux", "kill-session", "-t", SESSION], check=True)
    DAEMON_PID.unlink(missing_ok=True)
    print("Daemon gestoppt.")
    return 0


def cmd_daemon_status(namespace):
    print(f"Daemon: {'laeuft' if daemon_running() else 'gestoppt'}")
    print(f"tmux-Session '{SESSION}': {'aktiv' if is_session() else 'inaktiv'}")
    return 0


def cmd_daemon_restart(namespace):
    cmd_daemon_stop(namespace)
    time.sleep(1)
    return cmd_daemon_start(namespace)


def cmd_daemon_run(namespace):
    daemon_main()
    return 0


def cmd_attach(namespace):
    if not shutil.which("tmux"):
        tui()
        return 0
    if is_session():
        wait_for_session(timeout=2)
    elif daemon_running():
        wait_for_session()
    elif wait_for_session(timeout=8):
        pass
    else:
        start_daemon_process()
        wait_for_session()
    try:
        os.execvp("tmux", ["tmux", "attach-session", "-t", SESSION])
    except OSError as exc:
        print(f"Anhaengen fehlgeschlagen: {exc}", file=sys.stderr)
        return 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="termnotes",
        description="Notizen, die in einer Seitenleiste im Terminal angezeigt werden.",
    )
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Note hinzufuegen")
    add_p.add_argument("name", help="Name der Note")
    add_p.add_argument("text", nargs="+", help="Inhalt der Note")
    add_p.set_defaults(func=cmd_add)

    rm_p = sub.add_parser("rm", help="Note loeschen")
    rm_p.add_argument("name", help="Name der Note")
    rm_p.set_defaults(func=cmd_rm)

    list_p = sub.add_parser("list", help="Alle Notizen anzeigen")
    list_p.set_defaults(func=cmd_list)

    panel_p = sub.add_parser("panel", help="Notizen-Panel rendern (fuer tmux-Pane)")
    panel_p.set_defaults(func=cmd_panel)

    attach_p = sub.add_parser("attach", help="An die termnotes-Session anhaengen")
    attach_p.set_defaults(func=cmd_attach)

    size_p = sub.add_parser("setsize", help="Breite des Notizen-Panels in Prozent setzen")
    size_p.add_argument("percent", type=int, help="Prozent der Breite (10-80)")
    size_p.set_defaults(func=cmd_setsize)

    daemon_p = sub.add_parser("daemon", help="Daemon steuern (start/stop/status/restart/run)")
    daemon_sub = daemon_p.add_subparsers(dest="daemon_action", required=True)
    daemon_sub.add_parser("start").set_defaults(func=cmd_daemon_start)
    daemon_sub.add_parser("stop").set_defaults(func=cmd_daemon_stop)
    daemon_sub.add_parser("status").set_defaults(func=cmd_daemon_status)
    daemon_sub.add_parser("restart").set_defaults(func=cmd_daemon_restart)
    daemon_sub.add_parser("run").set_defaults(func=cmd_daemon_run)

    return parser


def tui():
    import curses

    notes = load_notes()
    selected = 0
    status = ""

    def notes_sorted():
        return sorted(notes.items(), key=lambda kv: kv[0].lower())

    def draw(stdscr):
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        if max_y < 5 or max_x < 30:
            stdscr.addstr(0, 0, "Terminal zu klein.")
            stdscr.refresh()
            return

        sidebar_w = max(28, int(max_x * 0.3))
        sidebar_w = min(sidebar_w, max_x - 16)
        border_y = max_y - 1

        for y in range(border_y):
            try:
                stdscr.addch(y, sidebar_w, curses.ACS_VLINE)
            except curses.error:
                pass

        stdscr.addstr(0, 2, "termnotes", curses.A_BOLD)
        stdscr.addstr(2, 2, "q  Beenden")
        stdscr.addstr(3, 2, "a  Note hinzufuegen")
        stdscr.addstr(4, 2, "d  Note loeschen")

        items = notes_sorted()
        if items:
            stdscr.addstr(6, 2, f"{len(items)} Notiz(en)")
        else:
            stdscr.addstr(6, 2, "Keine Notizen. Druecke 'a' zum Hinzufuegen.")

        if selected >= len(items):
            selected_index = 0
        else:
            selected_index = selected

        y = 8
        for i, (name, text) in enumerate(items):
            if y >= border_y - 2:
                break
            prefix = "> " if i == selected_index else "  "
            attr = curses.A_REVERSE if i == selected_index else 0
            x = 2
            try:
                stdscr.addstr(y, x, prefix, attr)
                x += len(prefix)
                name_part = f"{name}:"
                name_part = name_part[: sidebar_w - 1 - x]
                stdscr.addstr(y, x, name_part, attr | curses.A_BOLD)
                x += len(name_part)
                avail = sidebar_w - 1 - x
                stdscr.addstr(y, x, text[:avail], attr)
            except curses.error:
                pass
            y += 1

        title = " NOTES "
        stdscr.addstr(0, max(2, sidebar_w - len(title)), title, curses.A_REVERSE)

        if status:
            try:
                stdscr.addstr(border_y - 1, sidebar_w + 2, status[: max_x - sidebar_w - 3])
            except curses.error:
                pass

        stdscr.refresh()

    def read_input(prompt):
        max_y, _ = stdscr.getmaxyx()
        y = max_y - 2
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 0, prompt)
        curses.echo()
        curses.curs_set(1)
        try:
            stdscr.move(y, len(prompt))
            result = stdscr.getstr()
        finally:
            curses.noecho()
            curses.curs_set(0)
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        return result.decode("utf-8", "replace").strip()

    def show_prompt(msg):
        max_y, _ = stdscr.getmaxyx()
        stdscr.move(max_y - 1, 0)
        stdscr.clrtoeol()
        stdscr.addstr(max_y - 1, 0, msg)
        stdscr.refresh()

    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    curses.curs_set(0)

    try:
        while True:
            draw(stdscr)
            key = stdscr.getch()

            if key == ord("q"):
                break
            elif key in (curses.KEY_UP, ord("k")):
                if notes_sorted():
                    selected = (selected - 1) % len(notes_sorted())
            elif key in (curses.KEY_DOWN, ord("j")):
                if notes_sorted():
                    selected = (selected + 1) % len(notes_sorted())
            elif key == ord("a"):
                name = read_input("Name: ")
                if name:
                    text = read_input("Note: ")
                    if text:
                        notes[name] = text
                        save_notes(notes)
                        status = f"Note '{name}' gespeichert."
                    else:
                        status = "Abgebrochen."
                else:
                    status = "Abgebrochen."
            elif key == ord("d"):
                items = notes_sorted()
                if items:
                    idx = selected % len(items)
                    name = items[idx][0]
                    show_prompt(f"Note '{name}' loeschen? (j/N) ")
                    confirm = stdscr.getch()
                    if confirm in (ord("j"), ord("y"), ord("J"), ord("Y")):
                        del notes[name]
                        save_notes(notes)
                        status = f"Note '{name}' geloescht."
                        if selected > 0:
                            selected -= 1
                    else:
                        status = "Nicht geloescht."
    finally:
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()


def main(argv=None):
    parser = build_parser()
    namespace = parser.parse_args(argv)
    if namespace.command is None:
        return cmd_attach(namespace)
    return namespace.func(namespace)


if __name__ == "__main__":
    sys.exit(main())
