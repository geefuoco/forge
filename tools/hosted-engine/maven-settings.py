"""Write temporary Maven proxy settings from the inherited build environment."""
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

settings = ET.Element('settings', xmlns='http://maven.apache.org/SETTINGS/1.2.0')
address = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
if address:
    proxy = urlsplit(address)
    entry = ET.SubElement(ET.SubElement(settings, 'proxies'), 'proxy')
    for key, value in [('id', 'build-proxy'), ('active', 'true'), ('protocol', 'http'),
                       ('host', proxy.hostname), ('port', str(proxy.port or 80))]:
        ET.SubElement(entry, key).text = value
    if proxy.username:
        ET.SubElement(entry, 'username').text = unquote(proxy.username)
    if proxy.password:
        ET.SubElement(entry, 'password').text = unquote(proxy.password)
path = Path(sys.argv[1])
path.touch(mode=0o600, exist_ok=False)
ET.ElementTree(settings).write(path, encoding='unicode')
