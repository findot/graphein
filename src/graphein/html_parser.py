#!/usr/bin/env python

from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from markdownify import markdownify
import re

__all__ = ["WikipediaParser"]

STRIP_SELECTORS = [
    "#mw-navigation",
    "#toc",
    "#mw-head",
    "#mw-panel",
    "#p-lang-btn",
    ".mw-portlet",
    ".interlanguage-links",
    "nav",
    ".mw-editsection",
    "figure",
    ".thumb",
    "table.infobox",
    "table.sidebar",
    "table.ambox",
    "table.navbox",
    ".navbox",
    "table:has(> tbody > tr > td > .plainlinks)",
    "table.wikitable.floatright",
    ".IPA",
    ".mw-phonetic-content",
    ".noprint",
    ".hatnote",
    "#coordinates",
    "#catlinks",
    ".printfooter",
    ".mw-authority-control",
]

FOOTER_SECTIONS = (
    "See also",
    "Notes",
    "References",
    "Further reading",
    "External links",
)


@dataclass
class WikipediaParser:
    """
    Parses a Wikipedia HTML page into cleaned Markdown.

    Two output modes:
    - to_markdown(): preserves hyperlinks for human readability
    - to_plain_markdown(): strips all links, suitable for LLM ingestion
    """

    html: str
    _soup: BeautifulSoup = field(init=False, repr=False)
    _title: str = field(init=False, repr=False)

    def __post_init__(self):
        self._soup = self._parse()
        title_el = self._soup.select_one("#firstHeading")
        self._title = title_el.get_text().strip() if title_el else ""

    @property
    def title(self) -> str:
        return self._title

    def _parse(self) -> BeautifulSoup:
        soup = BeautifulSoup(self.html, "html.parser")

        for selector in STRIP_SELECTORS:
            for el in soup.select(selector):
                el.decompose()

        for a in soup.find_all("a", href=True):
            href = a.get("href")
            if not isinstance(href, str):
                a.unwrap()
                continue
            if href.startswith("/wiki/"):
                a["href"] = f"https://en.wikipedia.org{href}"
            elif not href.startswith("http"):
                a.unwrap()

        return soup

    def _body_markdown(self) -> str:
        body = self._soup.select_one("#mw-content-text") or self._soup
        md = markdownify(str(body), heading_style="ATX", strip=["img"])
        md = self._strip_footer(md)
        md = re.sub(r"\n{3,}", "\n\n", md).strip()
        return md

    @staticmethod
    def _strip_footer(text: str) -> str:
        pattern = "|".join(re.escape(s) for s in FOOTER_SECTIONS)
        match = re.search(rf"^## ({pattern})", text, re.MULTILINE)
        return text[: match.start()].strip() if match else text

    @staticmethod
    def _strip_links(text: str) -> str:
        return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    def _assemble(self, body: str) -> str:
        return f"# {self._title}\n\n{body}" if self._title else body

    def to_markdown(self) -> str:
        """Cleaned Markdown with hyperlinks preserved."""
        return self._assemble(self._body_markdown())

    def to_plain_markdown(self) -> str:
        """Cleaned Markdown with all links stripped — for LLM ingestion."""
        return self._assemble(self._strip_links(self._body_markdown()))
