"""Build, verify and archive a relocatable Windows application."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"Dhyana-95-V2-Portable_{stamp}"
    output = root / "dist" / name
    output.mkdir(parents=True, exist_ok=False)
    work = root / "build" / name
    work.mkdir(parents=True, exist_ok=False)
    build_log = work / "build.log"
    build_environment = dict(os.environ)
    if os.name == "nt":
        windows = Path(os.environ["SystemRoot"])
        # Do not collect unrelated DLLs (e.g. Poppler's ICU) from developer tools
        # on PATH. Qt uses the Windows ICU API, not those versioned ICU exports.
        build_environment["PATH"] = os.pathsep.join(map(str, [
            Path(sys.executable).parent, Path(sys.base_prefix),
            windows / "System32", windows,
        ]))
    build_environment.pop("TUCAM_BUILD_CONSOLE", None)
    print(f"Building {name}; log: {build_log}", flush=True)
    with build_log.open("w", encoding="utf-8") as log:
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", str(output), "--workpath", str(work), str(root / "tucam_portable.spec"),
        ], cwd=root, env=build_environment, stdout=log, stderr=subprocess.STDOUT, check=True)

    app = output / "Dhyana-95-V2-Camera-Control"
    config = json.loads((root / "config" / "user_settings.json").read_text(encoding="utf-8"))
    config["settings"].update(save_dir="data", remote_enabled=False, remote_token="", remote_allowed_ip="")
    (app / "config").mkdir()
    (app / "config" / "user_settings.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    for source in [root / "PORTABLE_README.txt", root / "README.md",
                   root / "scripts" / "create_portable_shortcut.ps1",
                   root / "scripts" / "create_portable_shortcut.cmd"]:
        shutil.copy2(source, app / source.name)
    examples = app / "examples"
    examples.mkdir()
    shutil.copy2(root / "docs" / "probes_0.5s_air_100um_candidates.csv", examples)

    report = work / "portable-self-test.json"
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", TUCAM_LOG_FILE="portable_self_test.log")
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # A different working directory verifies that paths resolve from the EXE.
    print("Checking packaged EXE, child processes and web resources...", flush=True)
    check = subprocess.run([
        str(app / "Dhyana-95-V2-Camera-Control.exe"), "--portable-self-test", str(report),
    ], cwd=work, env=environment, timeout=180, creationflags=creation_flags)
    result = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    print(f"Self-test exit={check.returncode}: {json.dumps(result, ensure_ascii=True)}", flush=True)
    if check.returncode or not result.get("ok"):
        raise RuntimeError(f"Portable self-test failed; see {report}")

    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root))
    metadata = {"built_at": datetime.now().astimezone().isoformat(), "base_commit": revision,
                "includes_uncommitted_changes": dirty, "python": sys.version,
                "self_test": result, "hardware_tested": False}
    (app / "BUILD_INFO.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = root / "dist" / f"{name}.zip"
    print(f"Creating {archive}", flush=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(app.rglob("*")):
            if path.is_file() and path.relative_to(app).parts[0] not in {"logs", "data"}:
                bundle.write(path, Path(name) / path.relative_to(app))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, "ZIP integrity check failed"
    digest_state = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest_state.update(chunk)
    digest = digest_state.hexdigest()
    archive.with_suffix(".sha256.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"READY: {archive}\nSIZE_MB: {archive.stat().st_size / 1024**2:.1f}\nSHA256: {digest}", flush=True)


if __name__ == "__main__":
    main()
