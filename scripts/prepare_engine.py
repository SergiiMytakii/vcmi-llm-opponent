"""Create a fresh, pinned VCMI checkout with our adapter; never reset an existing one."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run(*arguments, cwd=None):
    subprocess.run(arguments, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?", default=ROOT / ".build" / "vcmi")
    target = parser.parse_args().destination.resolve()
    if target.exists():
        parser.error(f"Destination already exists: {target}. Choose a fresh directory; existing work is preserved.")
    version = json.loads((ROOT / "engine" / "version.json").read_text())
    target.parent.mkdir(parents=True, exist_ok=True)
    run("git", "clone", "--filter=blob:none", "--no-checkout", version["repository"], str(target))
    run("git", "checkout", "--detach", version["revision"], cwd=target)
    run("git", "submodule", "update", "--init", "--depth", "1", "dependencies", cwd=target)
    dependency = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=target / "dependencies", text=True,
    ).strip()
    if dependency != version["dependencies_revision"]:
        raise RuntimeError("Dependency revision differs from the recorded build inputs")
    run("git", "apply", "--check", str(ROOT / "engine" / "integration.patch"), cwd=target)
    run("git", "apply", str(ROOT / "engine" / "integration.patch"), cwd=target)
    shutil.copytree(ROOT / "engine" / "ExternalAI", target / "AI" / "ExternalAI")
    print(f"Prepared {target} at {version['revision']}")


if __name__ == "__main__":
    main()
