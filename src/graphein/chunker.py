#!/usr/bin/env python

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    title: str  # document title
    section: str  # section heading
    subsection: str  # subsection heading, if any


def chunk_by_headings(markdown: str) -> list[Chunk]:
    title_match = re.match(r"^# (.+)$", markdown, re.MULTILINE)
    title = title_match.group(1) if title_match else ""

    # Split on ## headings
    sections = re.split(r"^(?=## )", markdown, flags=re.MULTILINE)

    chunks = []
    for section in sections:
        if not section.strip() or section.startswith("# "):
            continue

        heading_match = re.match(r"^## (.+)$", section, re.MULTILINE)
        section_title = heading_match.group(1) if heading_match else ""

        # Further split on ### subsections if the section is large
        subsections = re.split(r"^(?=### )", section, flags=re.MULTILINE)

        if len(subsections) > 1:
            for sub in subsections:
                if not sub.strip():
                    continue
                sub_match = re.match(r"^### (.+)$", sub, re.MULTILINE)
                sub_title = sub_match.group(1) if sub_match else ""
                chunks.append(
                    Chunk(
                        text=sub.strip(),
                        title=title,
                        section=section_title,
                        subsection=sub_title,
                    )
                )
        else:
            chunks.append(
                Chunk(
                    text=section.strip(),
                    title=title,
                    section=section_title,
                    subsection="",
                )
            )

    return chunks
