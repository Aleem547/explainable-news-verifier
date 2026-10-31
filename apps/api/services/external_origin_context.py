"""Bounded context for inspecting existing model inputs, never an origin proof."""

from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import re
import unicodedata
from urllib.parse import urljoin, urlsplit


class InspectionError(ValueError):
    pass


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def folded(value):
    text = unicodedata.normalize("NFKD", value).casefold()
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def public_reference(base, href):
    if not isinstance(href, str) or len(href) > 2048:
        return None
    try:
        url = urljoin(base, href)
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if (parts.scheme != "https" or port not in (None, 443) or not host
            or "." not in host or parts.username is not None or parts.password is not None
            or parts.query or "\\" in url or len(url) > 2048
            or any(c.isspace() or ord(c) < 32 for c in url)):
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None
    return parts._replace(fragment="").geturl()


@dataclass
class Block:
    text: list = field(default_factory=list)
    chars: int = 0
    capped: bool = False

    def add(self, value):
        remaining = 1200 - self.chars
        if len(value) > remaining:
            self.capped = True
        if remaining > 0:
            self.text.append(value[:remaining])
            self.chars += len(value[:remaining])

    def plain(self):
        return " ".join(" ".join(self.text).split())


class ArticleContext(HTMLParser):
    """Keep article and page limits separate; captions stay visibly distinct.

    HTML structure and bylines are publisher-supplied observations. No link is
    followed and no absence of links is interpreted as independent reporting.
    """

    VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
    SKIP = frozenset({"head", "script", "style", "textarea", "noscript", "template", "svg"})

    def __init__(self, base, limit=120):
        super().__init__(convert_charrefs=True)
        if not 1 <= limit <= 120:
            raise InspectionError("invalid_reference_limit")
        self.base, self.limit = base, limit
        self.stack = []
        self.records = {"article": [], "page": []}
        self.seen = {"article": set(), "page": set()}
        self.capped = {"article": False, "page": False}
        self.article_seen = False
        self.html_structure_capped = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        skipped = (tag in self.SKIP or any(f["skip"] for f in self.stack)
                   or "hidden" in attributes or str(attributes.get("aria-hidden", "")).casefold() == "true")
        article = not skipped and (tag == "article" or any(f["article"] for f in self.stack))
        if tag == "article" and not skipped:
            self.article_seen = True
        if tag in self.VOID:
            return
        if len(self.stack) >= 256:
            self.html_structure_capped = True
            return
        block = Block() if tag in {"p", "figcaption", "li"} and not skipped else None
        frame = {"tag": tag, "skip": skipped, "article": article, "block": block}
        if tag == "a" and not skipped:
            url = public_reference(self.base, attributes.get("href"))
            if url and url != self.base:
                caption = any(f["tag"] in {"figure", "figcaption"} for f in self.stack)
                navigation = any(f["tag"] in {"nav", "aside", "footer"} for f in self.stack)
                author = ("author" in attributes.get("rel", "").casefold().split()
                          or bool(re.search(r"/(?:authors?|people)/", urlsplit(url).path)))
                role = ("FIGURE_OR_CAPTION" if caption else
                        "NAVIGATION_OR_FOOTER" if navigation else
                        "BYLINE_PROFILE_LEAD" if author else "BODY_REFERENCE_LEAD")
                frame["anchor"] = {
                    "url": url, "role": role, "text": Block(),
                    "block": next((f["block"] for f in reversed(self.stack) if f["block"]), None),
                    "scope": "article" if article else "page",
                }
        self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if any(f["skip"] for f in self.stack):
            return
        for frame in self.stack:
            if frame["block"]:
                frame["block"].add(data)
            if frame.get("anchor"):
                frame["anchor"]["text"].add(data)

    def _close(self, frame):
        anchor = frame.get("anchor")
        if not anchor:
            return
        scope = anchor["scope"]
        key = (anchor["url"], anchor["role"])
        if key in self.seen[scope]:
            return
        self.seen[scope].add(key)
        if len(self.records[scope]) >= self.limit:
            self.capped[scope] = True
        else:
            self.records[scope].append(anchor)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                for frame in self.stack[index:]:
                    self._close(frame)
                del self.stack[index:]
                break

    def result(self, reviewed_author):
        for frame in self.stack:
            self._close(frame)
        scope = "article" if self.article_seen else "page"
        records = self.records[scope]
        host = urlsplit(self.base).hostname
        # Prioritize useful attribution leads rather than exporting page menus.
        order = {"BYLINE_PROFILE_LEAD": 0, "BODY_REFERENCE_LEAD": 1,
                 "FIGURE_OR_CAPTION": 2, "NAVIGATION_OR_FOOTER": 3}
        chosen = sorted(records, key=lambda r: (
            order[r["role"]], urlsplit(r["url"]).hostname == host, r["url"],
        ))[:16]
        leads = []
        for anchor in chosen:
            block = anchor["block"]
            context = block.plain() if block else ""
            leads.append({
                "url": anchor["url"], "role": anchor["role"],
                "anchor_text": anchor["text"].plain()[:120],
                "scope": scope,
                "context_excerpt": context[:240],
                "context_excerpt_truncated": bool(block and (block.capped or len(context) > 240)),
                "context_collected_prefix_sha256": digest(context) if context else None,
                "context_is_complete_block": bool(block and not block.capped),
            })
        bylines = [a for a in records if a["role"] == "BYLINE_PROFILE_LEAD"]
        matches = [a for a in bylines
                   if folded(a["text"].plain()) == folded(reviewed_author)]
        return {
            "collection_scope": "article_elements" if scope == "article" else "page_no_article_boundary",
            "article_reference_limit_reached": self.capped["article"],
            "page_reference_limit_reached": self.capped["page"],
            "selected_scope_reference_limit_reached": self.capped[scope],
            "html_structure_limit_reached": self.html_structure_capped,
            "references_in_selected_scope": len(records),
            "reference_details_export_capped": len(records) > len(chosen),
            "reference_leads": leads,
            "matching_byline_profile_lead_observed": bool(matches),
            "matching_byline_lead_scope": scope if matches else None,
            "reviewed_author": reviewed_author,
            "byline_leads_are_publisher_supplied": True,
            "photo_credits_are_not_text_origin_proof": True,
            "origin_authenticated": False,
            "independence_status": "NOT_ESTABLISHED",
        }

