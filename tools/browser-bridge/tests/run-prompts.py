import os
from pathlib import Path
import subprocess
import tempfile

tests = Path(__file__).resolve().parent
classpath = os.environ["FORGE_BRIDGE_CLASSPATH"]
sources = [tests.parent / "src/forge/browser/Bridge.java", tests / "PromptTest.java", tests / "AllocationTest.java", tests / "InputTest.java", tests / "RevisionTest.java", tests / "RevealTest.java", tests / "CompletionTest.java"]
with tempfile.TemporaryDirectory(prefix="forge-bridge-prompts-") as output:
    result = subprocess.run(["javac", "-cp", classpath, "-d", output, *map(str, sources)])
    if result.returncode:
        raise SystemExit(result.returncode)
    for name in ["PromptTest", "AllocationTest", "InputTest", "RevisionTest", "RevealTest", "CompletionTest"]:
        result = subprocess.run(["java", "-cp", output + os.pathsep + classpath, "forge.browser." + name], timeout=45)
        if result.returncode:
            raise SystemExit(result.returncode)
