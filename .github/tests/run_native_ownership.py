"""Unsigned macOS actual-source / full-SDK ownership regression."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "ec7ef9b405e4d2e9de06701e0bff18816ca9e76b"
SDK_SHA256 = "355ee208ad6c61dcc68e8432546fc42484888211dd07ed8fa3fdb4440f3edbd8"
CASES = ("file", "bytes", "copy", "gray", "size", "thumbnail", "return",
         "param", "array", "scalar", "conversion")
BASELINE_FAILURES = {
    "file": "double disposal or borrowed string disposal",
    "bytes": "leaked picture reference",
    "copy": "AddressSanitizer: heap-buffer-overflow",
    "gray": "leaked picture reference",
    "size": "leaked picture reference",
    "thumbnail": "leaked picture reference",
}


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true",
                        help="require named failures from the immutable pre-fix sources")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="bookmark-ownership-") as directory:
        work = Path(directory)
        root = ROOT
        if args.baseline:
            root = work / "baseline"
            files = subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", BASELINE,
                 "4D Plugin API", "4DPlugin.cpp", "4DPlugin.h"], cwd=ROOT, text=True)
            for name in files.splitlines():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(subprocess.check_output(
                    ["git", "show", f"{BASELINE}:{name}"], cwd=ROOT))
        sdk = root / "4D Plugin API"
        assert hashlib.sha256((sdk / "4DPluginAPI.c").read_bytes()).hexdigest() == SDK_SHA256
        executable = work / "ownership"
        sources = [sdk / "4DPluginAPI.c", *sorted((sdk / "Classes").glob("*.cpp")),
                   root / "4DPlugin.cpp", ROOT / ".github/tests/native_ownership.mm"]
        subprocess.run([
            "xcrun", "clang++", "-std=c++11", "-x", "objective-c++",
            "-include", "Carbon/Carbon.h", "-include", "cstring",
            "-I", str(sdk), "-I", str(sdk / "Classes"),
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-g", "-O1", "-Wno-deprecated-declarations",
            "-Wno-deprecated-register", "-Wno-return-type-c-linkage",
            *map(str, sources), "-framework", "Cocoa", "-framework", "Carbon",
            "-o", str(executable),
        ], check=True, cwd=ROOT)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0",
                           UBSAN_OPTIONS="halt_on_error=1")
        for case in CASES:
            modes = [(0, 0, 0)] if args.baseline else [
                (empty, noop, replace)
                for empty in (0, 1) for noop in (0, 1) for replace in (0, 1)]
            for mode in modes:
                result = subprocess.run([str(executable), case, *map(str, mode)],
                                        env=environment, text=True, capture_output=True)
                expected = BASELINE_FAILURES.get(case) if args.baseline else None
                if expected:
                    if result.returncode == 0 or expected not in result.stderr:
                        raise AssertionError(f"Missing baseline defect {case}:\n"
                                             f"{result.stdout}{result.stderr}")
                    print(f"EXPECTED BASELINE FAILURE {case}: {expected}", flush=True)
                else:
                    if result.returncode:
                        raise AssertionError(f"{case} failed:\n{result.stdout}{result.stderr}")
                    print(result.stdout.strip(), flush=True)
        print("Verified immutable baseline" if args.baseline else "Verified fixed sources",
              flush=True)


if __name__ == "__main__":
    run()
