"""Install a staged Halo update: wait for Halo to close, swap its files, start it again.

A running program can't replace its own files, so Halo starts this helper from the new
version's staged copy (``Halo.exe --apply-update <plan.json>``) and then quits. The helper:

1. writes the plan's "ready" file, so the old Halo knows the new copy starts and may quit;
2. waits for the old Halo to close;
3. moves the old program files into a backup folder inside the program folder, and copies
   the new ones in (``Halo.exe`` last, so the folder is without a program for the shortest time);
4. starts the new Halo and waits for it to write the plan's "healthy" file;
5. if the copy fails, or the new Halo closes or hangs before it is healthy, puts the old files
   back and starts the old Halo again.

Settings live outside the program folder (``%LOCALAPPDATA%\\Halo``), so nothing here touches them.
Only the standard library is used: this runs without Qt.

The plan format (``PROTOCOL``) must stay readable by every later release, because the helper
that installs an update always comes from the newer version.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PROTOCOL = 1
EXE = "Halo.exe"
# Top-level entries of a Halo package. The old ones go even when a new package leaves one out;
# anything else in the folder (a shortcut, the person's own files) is left alone.
PACKAGE_NAMES = ("Halo.exe", "_internal", "licenses", "docs", "README.md", "VERSION.txt", "source-manifest.json")
BACKUP_PREFIX = ".halo-previous"
FAILURE_NOTE = "UPDATE-FAILED.txt"
EXIT_TIMEOUT = 180.     # Halo closes its worker threads before it exits; allow for slow ones
HEALTH_TIMEOUT = 120.   # a first start after an update can be slow while antivirus scans the files
ACTIVE_PHASES = ("waiting", "swapping", "verifying")


class PlanError(ValueError):
    """The plan file is missing, from an unknown protocol, or points somewhere unsafe."""


class RestoreError(OSError):
    """The old files could not all be put back."""


def write_json(path, data, sleep=time.sleep):
    """Replace a small JSON file in one step, so a reader never sees half of it.

    Windows refuses to replace a file while anything has it open (Halo reading it, antivirus,
    the search indexer), so the replace is retried for a few seconds.
    """
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    retry(lambda: os.replace(temporary, path), attempts=60, delay=.05, sleep=sleep)


def read_json(path, sleep=time.sleep):
    """A small JSON object, or {} if there is none. A file held open for a moment is read again."""
    for attempt in range(20):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == 19:
                return {}
            sleep(.05)
            continue
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def retry(action, attempts=24, delay=.25, sleep=time.sleep):
    """Windows can hold a file for a moment after its program exits (antivirus, the search indexer)."""
    for attempt in range(attempts):
        try:
            return action()
        except (FileNotFoundError, FileExistsError, NotADirectoryError):
            raise
        except OSError:
            if attempt == attempts - 1:
                raise
            sleep(delay)


def remove(path, sleep=time.sleep):
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        retry(lambda: shutil.rmtree(path), sleep=sleep)
    elif path.exists() or path.is_symlink():
        retry(path.unlink, sleep=sleep)


def copy_entry(source, destination):
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def backup_folder(target):
    """A fresh backup folder name inside the program folder (same drive, so moving is a rename)."""
    for number in range(100):
        path = Path(target) / (BACKUP_PREFIX if number == 0 else f"{BACKUP_PREFIX}-{number}")
        if not path.exists():
            return path
    raise OSError("Too many old backup folders in " + str(target))


def _exe_last(names):
    """The libraries first, the program last."""
    return sorted(names, key=lambda name: (name == EXE, name != "_internal", name))


def swap(target, source, backup, copy=copy_entry, sleep=time.sleep):
    """Move the old program files into backup and copy the new ones from source.

    Returns (moved, installed) for restore(). On any failure the old files are put back before
    the error is raised again.
    """
    target, source, backup = Path(target), Path(source), Path(backup)
    new_names = sorted(entry.name for entry in source.iterdir())
    if EXE not in new_names:
        raise OSError(f"The new copy has no {EXE}")
    old_names = [name for name in set(new_names) | set(PACKAGE_NAMES)
                 if (target / name).exists() or (target / name).is_symlink()]
    backup.mkdir()
    moved, installed = [], []

    def put_aside(name):
        retry(lambda: os.replace(target / name, backup / name), sleep=sleep)
        moved.append(name)

    def bring_in(name):
        installed.append(name)  # first, so a half-finished copy is cleared away too
        copy(source / name, target / name)

    try:
        for name in _exe_last(old_names):
            if name != EXE:
                put_aside(name)
        for name in _exe_last(new_names):
            if name != EXE:
                bring_in(name)
        if EXE in old_names:
            put_aside(EXE)
        bring_in(EXE)
    except BaseException:
        restore(target, backup, moved, installed, sleep=sleep)
        raise
    return moved, installed


def restore(target, backup, moved, installed, sleep=time.sleep):
    """Undo swap(): clear what was copied in, and move the old files back."""
    target, backup = Path(target), Path(backup)
    problems = []
    for name in reversed(installed):
        try:
            remove(target / name, sleep=sleep)
        except OSError as error:
            problems.append(f"{name}: {error}")
    for name in reversed(moved):
        try:
            retry(lambda name=name: os.replace(backup / name, target / name), sleep=sleep)
        except OSError as error:
            problems.append(f"{name}: {error}")
    if problems:
        raise RestoreError("; ".join(problems))
    try:
        backup.rmdir()
    except OSError:
        pass


def wait_for_exit(pid, timeout):
    """True once the process has gone, False if it is still running after timeout seconds."""
    if os.name != "nt":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(.2)
        return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    synchronize = 0x00100000
    handle = kernel32.OpenProcess(synchronize, False, int(pid))
    if not handle:
        return True
    try:
        return kernel32.WaitForSingleObject(handle, int(max(0., timeout) * 1000)) == 0
    finally:
        kernel32.CloseHandle(handle)


def child_environment(environ=None):
    """The environment for a Halo started from another frozen Halo.

    PyInstaller passes its own variables to child processes; left in place, a new Halo could
    treat itself as part of the old one and load the old program's files. Qt's paths, set by the
    old copy's start-up hook, belong to that copy too.
    """
    env = dict(os.environ if environ is None else environ)
    for key in list(env):
        if key.upper().startswith("_PYI_") or key.upper() in ("_MEIPASS2", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            del env[key]
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def launch(exe, arguments=()):
    """Start a program on its own, so it keeps running after this process exits."""
    exe = Path(exe)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([str(exe), *arguments], cwd=str(exe.parent), env=child_environment(),
                            creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_until_healthy(process, healthy, version, timeout=HEALTH_TIMEOUT, sleep=time.sleep, clock=time.monotonic):
    """'healthy', 'exited' (closed before saying so) or 'timeout' (still silent, probably stuck on an error)."""
    deadline = clock() + timeout
    while True:
        if read_json(healthy).get("version") == version:
            return "healthy"
        if process.poll() is not None:
            return "healthy" if read_json(healthy).get("version") == version else "exited"
        if clock() >= deadline:
            return "timeout"
        sleep(.25)


def stop(process, sleep=time.sleep):
    """End a new Halo that never became healthy, so its files can be removed."""
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        for _ in range(80):
            if process.poll() is not None:
                break
            sleep(.25)
    sleep(.5)  # let Windows release the program's files


def load_plan(path):
    plan = read_json(path)
    if plan.get("protocol") != PROTOCOL:
        raise PlanError("Unknown update plan")
    required = ("pid", "target", "source", "state", "ready", "cancel", "healthy", "log", "to_version", "from_version")
    if any(key not in plan for key in required):
        raise PlanError("Incomplete update plan")
    target, source = Path(plan["target"]), Path(plan["source"])
    if not target.is_absolute() or not source.is_absolute():
        raise PlanError("Update paths must be absolute")
    resolved_target, resolved_source = target.resolve(), source.resolve()
    if resolved_source == resolved_target or resolved_source.is_relative_to(resolved_target) \
            or resolved_target.is_relative_to(resolved_source):
        raise PlanError("The new copy and the program folder overlap")
    if not (target / EXE).is_file():
        raise PlanError(f"The program folder has no {EXE}")
    if not (source / EXE).is_file() or not (source / "_internal").is_dir():
        raise PlanError("The new copy is incomplete")
    if not isinstance(plan["pid"], int) or isinstance(plan["pid"], bool):
        raise PlanError("The plan names no process")
    return plan


class Journal:
    """state.json: where the update stands, read by Halo when it starts again."""
    def __init__(self, path, plan, log):
        self.path, self.log = Path(path), log
        self.data = {"protocol": PROTOCOL, "from_version": plan.get("from_version"), "to_version": plan.get("to_version"),
                     "helper_pid": os.getpid(), "target": plan.get("target")}

    def write(self, phase, **details):
        self.data.update(details, phase=phase, updated_at=time.time())
        try:
            write_json(self.path, self.data)
        except OSError as error:
            self.log(f"Could not write the update state: {error}")
        self.log(f"phase {phase}" + (f" {details}" if details else ""))


def make_log(path):
    def log(message):
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
        except OSError:
            pass
    return log


def leave_note(target, backup, reason, log):
    """If the folder could not be put back, say where the old copy is, beside Halo.exe."""
    try:
        (Path(target) / FAILURE_NOTE).write_text(
            "Halo's update could not finish, and the previous version could not be put back.\n"
            f"The previous version's files are in: {backup}\n"
            "Move them back into this folder, or download Halo again from "
            "https://github.com/lmaoitsatharv/halo/releases/latest\n\n"
            f"Details: {reason}\n", encoding="utf-8")
    except OSError as error:
        log(f"Could not leave a note: {error}")


def run(plan_path, *, wait_exit=wait_for_exit, start=launch, copy=copy_entry, sleep=time.sleep,
        clock=time.monotonic, exit_timeout=EXIT_TIMEOUT, health_timeout=HEALTH_TIMEOUT):
    """Carry out a plan. Returns 0 when the new version runs, and another number otherwise."""
    try:
        plan = load_plan(plan_path)
    except PlanError as error:
        make_log(Path(plan_path).with_name("update.log"))(f"Plan refused: {error}")
        return 10
    log = make_log(plan["log"])
    journal = Journal(plan["state"], plan, log)
    target, source = Path(plan["target"]), Path(plan["source"])
    version = str(plan["to_version"])
    journal.write("waiting", result=None, reason="")
    try:
        write_json(plan["ready"], {"helper_pid": os.getpid()})
    except OSError as error:
        journal.write("done", result="unchanged", reason=f"Could not signal Halo: {error}")
        return 11
    if not wait_exit(plan["pid"], exit_timeout):
        journal.write("aborted", result="unchanged", reason="Halo did not close")
        return 12
    if Path(plan["cancel"]).exists():
        journal.write("cancelled", result="unchanged", reason="Halo cancelled the update")
        return 13
    sleep(.5)  # Windows releases a closed program's files a moment after it exits
    backup = backup_folder(target)
    journal.write("swapping", backup=str(backup))
    try:
        moved, installed = swap(target, source, backup, copy=copy, sleep=sleep)
    except RestoreError as error:
        journal.write("done", result="broken", reason=str(error))
        leave_note(target, backup, error, log)
        return 14
    except Exception as error:
        journal.write("done", result="unchanged", reason=f"Halo's files could not be replaced: {error}")
        _start_quietly(start, target / EXE, log)
        return 15
    try:
        Path(plan["healthy"]).unlink(missing_ok=True)
    except OSError:
        pass
    journal.write("verifying")
    try:
        process = start(target / EXE)
    except OSError as error:
        process, outcome = None, f"could not start: {error}"
    else:
        outcome = wait_until_healthy(process, plan["healthy"], version, health_timeout, sleep, clock)
    if outcome == "healthy":
        try:
            remove(backup, sleep=sleep)
        except OSError as error:
            log(f"The old copy stays in {backup} for now: {error}")
        journal.write("done", result="updated", reason="")
        return 0
    reason = {"exited": "The new version closed while starting",
              "timeout": "The new version did not finish starting"}.get(outcome, f"The new version {outcome}")
    if process is not None:
        stop(process, sleep=sleep)
    try:
        restore(target, backup, moved, installed, sleep=sleep)
    except RestoreError as error:
        journal.write("done", result="broken", reason=f"{reason}; putting the old version back failed: {error}")
        leave_note(target, backup, error, log)
        return 16
    journal.write("done", result="rolled_back", reason=reason)
    _start_quietly(start, target / EXE, log)
    return 17


def _start_quietly(start, exe, log):
    try:
        start(exe)
    except OSError as error:
        log(f"Could not start {exe}: {error}")


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 2 or arguments[0] != "--apply-update":
        return 2
    try:
        return run(arguments[1])
    except Exception as error:  # never let a frozen, windowed helper stop on an error box
        make_log(Path(arguments[1]).with_name("update.log"))(f"Helper failed: {error!r}")
        return 19
