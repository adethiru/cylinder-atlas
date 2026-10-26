"""Real tools the Scout agent can call: fetch a page from the target's own
website, read the investor's pasted notes, and record a verified fact."""
from __future__ import annotations

import gzip
import re
import ssl
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from . import config, db, safety
from .net import ssl_context

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 CylinderAtlas-research/1.0")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self, base):
        super().__init__()
        self.base, self.out, self.links, self._skip = base, [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                self.links.append(urljoin(self.base, href))
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div", "section"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(html: str, base: str) -> tuple[str, list[str]]:
    p = _Text(base)
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text, p.links


def _download(url: str) -> str:
    if url.startswith("local:"):
        path = url.split(":", 1)[1].strip("/")
        site, _, page = path.partition("/")
        f = config.DEMO_SITE_DIR / site / ((page or "index") + ".html")
        if not f.resolve().is_relative_to(config.DEMO_SITE_DIR.resolve()) or not f.exists():
            raise FileNotFoundError(f"No such demo page: {url}")
        return f.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                                 "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"})
    ctx = ssl_context()
    try:
        r = urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT, context=ctx)
    except ssl.SSLError:
        r = urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT, context=ssl._create_unverified_context())
    with r:
        raw = r.read(2_000_000)
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype and "text" not in ctype:
            raise ValueError(f"Not an HTML page ({ctype})")
        return raw.decode(r.headers.get_content_charset() or "utf-8", errors="ignore")


class ScoutSession:
    """Holds the per-run state the tools need (allowed domain, page budget,
    the raw text the agent has seen - used later to verify quotes)."""

    def __init__(self, target: dict, run_id: int, page_chars: int = None):
        self.t, self.run_id = target, run_id
        self.pages_used = 0
        self.seen_text = ""          # everything the agent was shown (for quote checks)
        self.page_chars = page_chars or config.PAGE_CHAR_BUDGET
        self.facts_saved = 0
        self.rejected = 0

    # ---- tool: fetch_page ----------------------------------------------------
    def fetch_page(self, url: str) -> str:
        site = self.t.get("website") or ""
        if site.startswith("local:") and not url.startswith(("local:", "http:", "https:", "file:", "ftp:")):
            url = site + ("/" + url.strip("/") if url and url not in ("/", site) else "")
        ok, why = safety.allowed_url(url, site, self.t.get("source") or "")
        if not ok:
            db.security_event("domain_blocked", f"{url} -> {why}", self.run_id, self.t["id"])
            db.add_step(self.run_id, "guard", "blocked", "Domain allow-list blocked a page", f"{url}\n{why}")
            return f"BLOCKED: {why}"
        if self.pages_used >= config.MAX_PAGES_PER_RUN:
            return f"LIMIT: page budget of {config.MAX_PAGES_PER_RUN} pages reached. Record facts and finish."
        self.pages_used += 1
        try:
            html = _download(url)
        except Exception as e:  # noqa: BLE001
            return f"ERROR fetching {url}: {str(e)[:200]}"
        text, links = html_to_text(html, url if not url.startswith("local:") else "")
        full_len = len(text)
        text = text[: self.page_chars]
        wrapped, hits = safety.sanitize_untrusted(text)
        if hits:
            db.security_event("prompt_injection", f"{url}: {hits}", self.run_id, self.t["id"])
            db.add_step(self.run_id, "guard", "blocked",
                        f"Injection filter removed {len(hits)} suspicious line(s)", "\n".join(hits))
        self.seen_text += "\n" + text
        if site.startswith("local:"):
            same = [l for l in links if l.startswith("local:")]
        else:
            dom = safety.domain_of(site)
            same = sorted({l.split("#")[0] for l in links if safety.domain_of(l).endswith(dom)})[:20]
        return (f"URL: {url}\nCHARS: {len(text)} of {full_len} (truncated to page budget)\n"
                f"{wrapped}\nLINKS ON THIS SITE:\n" + "\n".join(same))

    # ---- tool: read_investor_notes ---------------------------------------------
    def read_investor_notes(self) -> str:
        notes = (self.t.get("investor_notes") or "").strip()
        if not notes:
            return "No investor notes for this target."
        self.seen_text += "\n" + notes
        return "INVESTOR NOTES (trusted):\n" + notes[:4000]

    # ---- tool: record_fact ---------------------------------------------------------
    def record_fact(self, field: str, value: str, quote: str, source_url: str = "") -> str:
        if self.facts_saved >= config.MAX_FACTS:
            return "LIMIT: max facts reached. Finish now."
        ok = safety.verify_quote(quote or "", self.seen_text)
        db.x("INSERT INTO facts (target_id,field,value,quote,source_url,verified,created) VALUES (?,?,?,?,?,?,?)",
             (self.t["id"], field, str(value)[:500], (quote or "")[:500], source_url, 1 if ok else 0, time.time()))
        if not ok:
            self.rejected += 1
            db.security_event("fact_rejected", f"{field}={value!r}; quote not found: {quote!r}", self.run_id, self.t["id"])
            db.add_step(self.run_id, "guard", "blocked", f"Fact rejected (quote not in source): {field}",
                        f"value: {value}\nquote: {quote}")
            return "REJECTED: that quote does not appear in any page or notes you were given. Only record facts you can quote exactly."
        self.facts_saved += 1
        return f"SAVED fact {field}."


TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Fetch cleaned text of a page on the target's OWN website, or the single directory page given as the target's `source` (other domains are blocked).",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "read_investor_notes",
        "description": "Read notes the investor pasted about this target (teaser, call notes).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "record_fact",
        "description": "Save one fact with an exact supporting quote copied from a page or notes.",
        "parameters": {"type": "object", "properties": {
            "field": {"type": "string"}, "value": {"type": "string"},
            "quote": {"type": "string", "description": "8-40 words copied verbatim from the source text"},
            "source_url": {"type": "string"}},
            "required": ["field", "value", "quote", "source_url"]}}},
]
