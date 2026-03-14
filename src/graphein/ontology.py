#!/usr/bin/env python
from dataclasses import dataclass, field

import json
import os
import random
from pathlib import Path

from graphrag_sdk import KnowledgeGraph, Ontology
from graphrag_sdk.model_config import KnowledgeGraphModelConfig
from graphrag_sdk.models.litellm import LiteModel
from graphrag_sdk.source import AbstractSource, TEXT

__all__ = ["OntologyBuilder", "GraphSession", "sources_from_dir", "make_model"]


BOUNDARIES = """
Extract entities and relationships relevant to the subject matter.
Avoid creating entities for things that are better expressed as attributes.
Prefer specific relationship types over generic ones like HAS or IS_RELATED_TO.
Use consistent relationship type names for the same semantic concept across all documents.
When extracting a relationship between two entities, be exhaustive — extract all instances
of that relationship type present in the passage, or none. Never extract a partial subset.
Do not create relationships that are fully derivable from other relationships already present:
- Do not create SIBLING_OF, ANCESTOR_OF, or DESCENDANT_OF if PARENT_OF is present.
- Do not create MEMBER_OF if hierarchical containment relationships are present.
Prefer relationships that carry information not already encoded elsewhere in the graph.
"""


class OntologyBuilder:
    """Named constructors for Ontology — no direct instantiation."""

    def __init__(self):
        raise TypeError("Use OntologyBuilder.discover() or OntologyBuilder.from_file()")

    @staticmethod
    def discover(
        sources: list[AbstractSource],
        model: LiteModel,
        sample_ratio: float = 0.4,
        boundaries: str = BOUNDARIES,
    ) -> Ontology:
        sampled = random.sample(sources, max(3, round(len(sources) * sample_ratio)))
        return Ontology.from_sources(
            sources=sampled,
            boundaries=boundaries,
            model=model,
        )

    @staticmethod
    def from_file(path: Path) -> Ontology:
        return Ontology.from_json(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def save(ontology: Ontology, path: Path) -> None:
        path.write_text(json.dumps(ontology.to_json(), indent=2), encoding="utf-8")


@dataclass
class GraphSession:
    graph_name: str
    ontology: Ontology
    model_name: str = "claude-sonnet-4-5"
    host: str = "localhost"
    port: int = 6379
    _model: LiteModel = field(init=False, repr=False)
    _kg: KnowledgeGraph = field(init=False, repr=False)

    def __post_init__(self):
        self._model = LiteModel(
            self.model_name,
            additional_params={"api_key": os.getenv("ANTHROPIC_API_KEY")},
        )
        self._kg = KnowledgeGraph(
            name=self.graph_name,
            model_config=KnowledgeGraphModelConfig.with_model(self._model),
            ontology=self.ontology,
            host=self.host,
            port=self.port,
            username=os.getenv("FALKORDB_USERNAME"),
            password=os.getenv("FALKORDB_PASSWORD"),
        )

    def ingest(self, sources: list[AbstractSource]) -> None:
        self._kg.process_sources(sources)

    def query(self, message: str) -> str:
        return self._kg.chat_session().send_message(message)["response"]

    def chat(self):
        return self._kg.chat_session()


def make_model(model_name: str = "claude-sonnet-4-5") -> LiteModel:
    return LiteModel(
        model_name,
        additional_params={"api_key": os.getenv("ANTHROPIC_API_KEY")},
    )


def sources_from_dir(input_dir: Path) -> list[AbstractSource]:
    return [TEXT(str(f)) for f in input_dir.glob("*.llm.md")]
