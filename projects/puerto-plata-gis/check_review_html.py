"""Validate inline JavaScript syntax for both review UIs using local Node.js."""
from __future__ import annotations
import argparse
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts = []
        self.active = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        values = dict(attrs)
        if values.get("src"):
            self.capture = False
            return
        self.active = []
        self.capture = True

    def handle_data(self, data):
        if self.capture:
            self.active.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            self.parts.append("".join(self.active))
            self.capture = False

def check(path):
    body=path.read_text(encoding="utf-8")
    collector=ScriptCollector()
    collector.feed(body)
    if not collector.parts or not any(part.strip() for part in collector.parts):
        raise ValueError(f"No inline scripts in {path}")
    for script in collector.parts:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",suffix=".js") as handle:
            handle.write(script)
            handle.flush()
            result=subprocess.run(["node","--check",handle.name],capture_output=True,text=True)
            if result.returncode:
                raise RuntimeError(f"Invalid JavaScript {path}: {result.stderr}")
    return len(collector.parts)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("html",type=Path,nargs="+")
    files=p.parse_args().html
    for path in files:
        count=check(path)
        print(f"JS syntax OK: {path}: {count} inline script(s)")

if __name__=="__main__":
    main()
