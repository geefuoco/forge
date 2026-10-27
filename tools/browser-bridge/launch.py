#!/usr/bin/env python3
"""Compile and launch the local Forge browser bridge."""
import argparse
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
desktop = root / "forge-gui-desktop"
out = desktop / "target" / "browser-bridge"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--origin", required=True, help="HTTPS origin of the private Site")
parser.add_argument("--profile", type=Path, default=Path.home() / ".neoforge" / "bridge-profile",
                    help="Private persistent engine profile directory")
args = parser.parse_args()

java = shutil.which("java")
javac = shutil.which("javac")
if not java or not javac:
    sys.exit("Java and javac from a JDK must be on PATH.")
if not (desktop / "target" / "classes").is_dir():
    sys.exit("Forge is not built. Run the Maven build in the bridge README first.")
out.mkdir(parents=True, exist_ok=True)
classpath = os.environ.get("FORGE_BRIDGE_CLASSPATH")
if not classpath:
    maven = shutil.which("mvn") or shutil.which("mvn.cmd")
    if not maven:
        sys.exit("Maven must be on PATH to resolve Forge dependencies.")
    cpfile = out / "classpath.txt"
    subprocess.run([maven, "-q", "dependency:build-classpath", "-Dmdep.outputFile=" + str(cpfile)], cwd=desktop, check=True)
    classpath = str(desktop / "target" / "classes") + os.pathsep + cpfile.read_text().strip()
source = root / "tools" / "browser-bridge" / "src" / "forge" / "browser" / "Bridge.java"
subprocess.run([javac, "-cp", classpath, "-d", str(out), str(source)], cwd=desktop, check=True)
profile = args.profile.expanduser().resolve()
profile.mkdir(parents=True, exist_ok=True)
runtime_env = dict(os.environ)
runtime_env["APPDATA"] = str(profile / "AppData" / "Roaming")
runtime_env["LOCALAPPDATA"] = str(profile / "AppData" / "Local")
pom = ET.parse(desktop / "pom.xml")
module_options = pom.findtext("m:properties/m:addopen.java.args", default="", namespaces={"m": "http://maven.apache.org/POM/4.0.0"})
subprocess.run([java, *shlex.split(module_options), "-Duser.home=" + str(profile),
                "-cp", str(out) + os.pathsep + classpath, "forge.browser.Bridge", args.origin],
               cwd=desktop, env=runtime_env, check=True)
