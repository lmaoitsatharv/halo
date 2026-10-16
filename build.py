"""Build a portable folder and ZIP with dependency notices and a native icon."""
import importlib.metadata
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile
import hashlib
import tempfile
import json
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication
from halo.app import make_icon

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--dist-dir", help="Build into a staging directory for a running-app update")
parser.add_argument("--reuse-analysis", action="store_true", help="Skip cache cleanup; source and work files remain isolated")
args = parser.parse_args()
dist_dir = Path(args.dist_dir).resolve() if args.dist_dir else root / "dist"
# Freeze all runtime modules, and keep each packaging job's work/cache separate.
# Concurrent Halo changes must never mix old controller code with new widgets.
(root / ".staging").mkdir(exist_ok=True)
job_dir = Path(tempfile.mkdtemp(prefix="halo-build-", dir=root / ".staging"))
snapshot_dir = job_dir / "source"
snapshot_dir.mkdir()
for attempt in range(3):
    runtime_files = [root / "main.py", *sorted((root / "halo").glob("*.py"))]
    before = {str(file.relative_to(root)): hashlib.sha256(file.read_bytes()).hexdigest() for file in runtime_files}
    for file in runtime_files:
        destination = snapshot_dir / file.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, destination)
    after = {str(file.relative_to(root)): hashlib.sha256(file.read_bytes()).hexdigest() for file in runtime_files}
    captured = {name: hashlib.sha256((snapshot_dir / name).read_bytes()).hexdigest() for name in before}
    current_files = [root / "main.py", *sorted((root / "halo").glob("*.py"))]
    if before == after == captured and current_files == runtime_files:
        break
else:
    raise RuntimeError("Source is changing during packaging. Retry when edits settle.")
(job_dir / "source-manifest.json").write_text(json.dumps(captured, indent=2), encoding="utf-8")
app = QApplication([])
buffer = QBuffer()
buffer.open(QIODevice.OpenModeFlag.WriteOnly)
make_icon().pixmap(64, 64).save(buffer, "PNG")
png = bytes(buffer.data())
icon = job_dir / "halo.ico"
icon.write_bytes(struct.pack("<HHH", 0, 1, 1) +
                 struct.pack("<BBBBHHII", 64, 64, 0, 0, 1, 32, len(png), 22) + png)
# Do not let unrelated native DLLs on a developer's PATH leak into the bundle.
build_env = os.environ.copy()
build_env.pop("PYTHONPATH", None)
build_env["PYINSTALLER_CONFIG_DIR"] = str(job_dir / "cache")
windows_dir = Path(os.environ.get("SystemRoot", "C:/Windows"))
build_env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent),
    str(root / ".venv/Lib/site-packages/PySide6"), str(windows_dir / "System32"), str(windows_dir)])
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
           "--distpath", str(dist_dir), "--workpath", str(job_dir / "work"), "--specpath", str(job_dir),
           "--paths", str(snapshot_dir), "--name", "Halo", "--icon", str(icon),
           "--collect-submodules", "winrt", "--copy-metadata", "soundcard", str(snapshot_dir / "main.py")]
if not args.reuse_analysis:
    command.insert(3, "--clean")
subprocess.run(command, cwd=snapshot_dir, env=build_env, check=True)
target = dist_dir / "Halo"
shutil.copy2(root / "README.md", target / "README.md")
if (root / "docs").is_dir():
    shutil.copytree(root / "docs", target / "docs", dirs_exist_ok=True)
shutil.copy2(job_dir / "source-manifest.json", target / "source-manifest.json")
for dist in importlib.metadata.distributions():
    for file in dist.files or []:
        name = str(file).replace("\\", "/")
        if "license" in name.casefold() or name.casefold().endswith(("copying", "notice")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                clean = Path(*[part for part in Path(name).parts if part not in ("..", ".")])
                destination = target / "licenses" / dist.metadata["Name"] / clean
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
zip_path = dist_dir / "Halo-Windows-x64.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in target.rglob("*"):
        if file.is_file():
            archive.write(file, file.relative_to(target.parent))
print(f"Portable ZIP: {zip_path} ({zip_path.stat().st_size / 1024**2:.1f} MB)")
