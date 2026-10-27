import argparse
from pathlib import Path
import subprocess
import zipfile

parser = argparse.ArgumentParser(description="Package the Forge browser companion source.")
parser.add_argument("--forge-root", type=Path, required=True)
args = parser.parse_args()
forge = args.forge_root.resolve()
source = forge / "tools" / "browser-bridge"
if not source.is_dir():
    parser.error("The Forge checkout must contain tools/browser-bridge.")
output = Path(__file__).resolve().parents[1] / "dist" / "downloads" / "neoforge-companion-source.zip"
output.parent.mkdir(parents=True, exist_ok=True)
revision = subprocess.check_output(["git", "-C", str(forge), "rev-parse", "HEAD"], text=True).strip()
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(forge))
    archive.write(forge / "LICENSE", "LICENSE")
    archive.writestr("START-HERE.txt", "Extract into the root of your Forge checkout. Read tools/browser-bridge/README.md.\n"
                     "This is companion source, not a standalone engine.\nBridge source commit " + revision + "\n")
print(output)
