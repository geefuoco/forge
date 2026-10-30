import os
from pathlib import Path
import subprocess
import tempfile

tests = Path(__file__).resolve().parent
classpath = os.environ["FORGE_BRIDGE_CLASSPATH"]
names = ["PromptTest", "AllocationTest", "InputTest", "RevisionTest", "RevealTest", "CompletionTest", "HostedTest", "CardPresentationTest"]
sources = [tests.parent / "src/forge/browser/Bridge.java", *(tests / (name + ".java") for name in names)]
with tempfile.TemporaryDirectory(prefix="forge-bridge-prompts-") as output:
    result = subprocess.run(["javac", "-cp", classpath, "-d", output, *map(str, sources)])
    if result.returncode:
        raise SystemExit(result.returncode)
    for name in names:
        result = subprocess.run(["java", "-cp", output + os.pathsep + classpath, "forge.browser." + name], timeout=45)
        if result.returncode:
            raise SystemExit(result.returncode)
