"""Keeps the Content Security Policy in index.html in sync with its inline script.

The policy only lets the page run the exact inline <script> it ships with (by its sha256 hash), so
injected markup like <img onerror=...> can never run code. Any edit to the script changes the hash:
run `python3 tools/csp.py` after editing, or the app will refuse to run its own script.
`python3 tools/csp.py --check` fails if the hash is stale (used in CI).
"""
import base64
import hashlib
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "index.html"
POLICY = ("default-src 'none'; script-src '{hash}'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
          "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' https:; manifest-src 'self'; "
          "worker-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'")


def main():
    html = INDEX.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if len(scripts) != 1 or html.count("<script") != 1:
        sys.exit("index.html must have exactly one inline <script> and no other script tags")
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
    meta = '<meta http-equiv="Content-Security-Policy" content="%s">' % POLICY.format(hash="sha256-" + digest)
    if html.count('http-equiv="Content-Security-Policy"') != 1:
        sys.exit('index.html must have exactly one <meta http-equiv="Content-Security-Policy" content="..."> tag')
    new, n = re.subn(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">', meta, html, count=1)
    if n != 1:  # fail closed: a missing or reordered tag must never pass as "ok"
        sys.exit('CSP meta tag not found in the expected form: <meta http-equiv="Content-Security-Policy" content="...">')
    if "--check" in sys.argv:
        if new != html:
            sys.exit("CSP hash in index.html is stale: run python3 tools/csp.py")
        print("CSP ok")
        return
    INDEX.write_text(new, encoding="utf-8")
    print("CSP updated: sha256-" + digest)


if __name__ == "__main__":
    main()
