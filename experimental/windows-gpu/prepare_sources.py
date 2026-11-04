"""Fetch pinned public sources and apply the reviewed experimental patches."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess

HERE = pathlib.Path(__file__).resolve().parent

def run(*args, cwd=None):
    argv = [str(a) for a in args]
    if argv[0] == "git" and cwd is not None:
        argv[1:1] = ["-c", "safe.directory=" + pathlib.Path(cwd).as_posix()]
    subprocess.run(argv, cwd=cwd, check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--clang", default="clang", help="LLVM clang executable for owned AIR fixtures")
    parser.add_argument("--skip-fixtures", action="store_true", help="Prepare source only; GPU example tests will need fixtures")
    parser.add_argument("--qemu-submodules", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((HERE / "sources.json").read_text())
    entries = manifest["sources"] + [dict(manifest["test_dependency"], base_commit=manifest["test_dependency"]["commit"])]
    destination = args.destination.resolve()
    if any((destination / e["directory"]).exists() for e in entries):
        raise RuntimeError("A source directory already exists; choose a new destination. Nothing was overwritten.")
    if not args.skip_fixtures and not shutil.which(args.clang):
        raise RuntimeError("LLVM clang is required; pass --clang with its path or --skip-fixtures")
    destination.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        tree = destination / entry["directory"]
        run("git", "init", "-q", tree)
        run("git", "config", "core.autocrlf", "false", cwd=tree)
        run("git", "remote", "add", "origin", entry["url"], cwd=tree)
        run("git", "fetch", "--depth", "1", "origin", entry["base_commit"], cwd=tree)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=tree)
        if "patch" in entry:
            patch = HERE / entry["patch"]
            if hashlib.sha256(patch.read_bytes()).hexdigest() != entry["patch_sha256"]:
                raise RuntimeError("Patch digest mismatch: " + entry["patch"])
            run("git", "apply", "--check", patch, cwd=tree)
            run("git", "apply", patch, cwd=tree)
            for name, expected in entry["files"].items():
                actual = hashlib.sha256((tree / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                if actual != expected:
                    raise RuntimeError("Reconstructed source mismatch: " + name)
        if args.qemu_submodules and entry["directory"] == "qemu-vphone-windows":
            run("git", "submodule", "update", "--init", "--recursive", cwd=tree)
    if not args.skip_fixtures:
        examples = destination / "metal2vulkan-ios-container/crates/metal2vulkan-runtime/examples"
        shutil.copy2(HERE / "fixtures/rgb444_render_probe.ll", examples / "rgb444_render_probe.ll")
        for name in ["rgb444_probe", "rgb444_render_probe"]:
            run(args.clang, "-Wno-override-module", "-target", "x86_64-pc-windows-msvc", "-x", "ir", "-c", "-emit-llvm", examples / (name + ".ll"), "-o", examples / (name + ".bc"))
    print("Pinned source preparation complete. No guest disk was opened and no VM was started.")

if __name__ == "__main__":
    main()
