#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export NEO_FORGE_PROJECT_DIR="$project_dir"
python3 - <<'PY'
import json
import os
from pathlib import Path

project = Path(os.environ['NEO_FORGE_PROJECT_DIR'])
java = Path(os.environ.get('NEO_FORGE_JAVA_HOME', '/workspace/.tools/sysroot/usr/lib/jvm/java-21-openjdk-amd64'))
maven = Path(os.environ.get('NEO_FORGE_MAVEN_HOME', '/workspace/.tools/apache-maven-3.9.11'))
settings = Path(os.environ.get('NEO_FORGE_MAVEN_SETTINGS', '/workspace/.tools/maven-settings.xml'))
for required in (java / 'bin/java', java / 'bin/javac', maven / 'bin/m2.conf', settings):
    if not required.is_file():
        raise SystemExit(f'Missing cloud toolchain file: {required}')
tools = project / '.tools'
tools.mkdir(exist_ok=True)
config = {'javaHome': str(java), 'mavenHome': str(maven), 'mavenSettings': str(settings)}
(tools / 'toolchain.json').write_text(json.dumps(config, indent=2) + '\n')
cache = tools / 'm2'
shared_cache = Path('/workspace/.m2/repository')
if shared_cache.is_dir() and not cache.exists() and not cache.is_symlink():
    cache.symlink_to(shared_cache, target_is_directory=True)
print(f'Configured cloud toolchain in {tools / "toolchain.json"}')
PY
