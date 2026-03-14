# Graphein — GraphRAG Pipeline

A GraphRAG pipeline that transforms a corpus of HTML documents into a queryable knowledge graph stored in FalkorDB, using LLM-based ontology discovery and entity extraction.

## Concept

Traditional RAG retrieves text chunks by vector similarity. GraphRAG adds a knowledge graph layer: entities and relationships extracted from documents become nodes and edges, enabling retrieval that follows semantic *and* structural paths. A query about "Zeus's siblings" can traverse `PARENT_OF` edges rather than relying on the phrase "sibling" appearing near "Zeus" in a chunk.

The key design decision in this pipeline is **ontology discovery rather than ontology design**: the graph schema is inferred from the corpus itself via LLM sampling, then reviewed by a human before full ingestion. This avoids the need to deeply understand the corpus before building the graph.

## Architecture

```
HTML documents
     │
     ▼
WikipediaParser          (bs4 + markdownify)
     │  ├── to_markdown()          → human-readable .md with links
     │  └── to_plain_markdown()    → LLM-ready .md, links stripped
     ▼
OntologyBuilder
     │  ├── discover()             → samples corpus, LLM infers schema
     │  ├── save() / from_file()   → persist for human review
     ▼
     [HUMAN REVIEW of ontology.json]
     ▼
GraphSession
     │  ├── ingest()               → LLM extracts entities/relations per ontology
     │  ├── query()                → single question → Cypher → answer
     │  └── chat()                 → multi-turn session
     ▼
FalkorDB (property graph)
```

### Key design principles

**Extraction vs. inference separation.** The graph stores only what is explicitly stated in the corpus (ABox). Relationships that are logically derivable — siblings from shared parents, ancestors from transitive parentage — are intentionally *not* extracted. They are inferred at query time via graph traversal, or materialised in a post-ingestion enrichment pass. This avoids partial relationship coverage, which is worse than no coverage.

**All or nothing on relationships.** The extraction boundaries instruct the LLM to extract all instances of a relationship type present in a passage, or none. A partial subset (e.g. one sibling out of five) creates false completeness and degrades query quality.

**Two Markdown representations.** The HTML parser produces two outputs from the same parse: a human-readable version with hyperlinks for browsability, and a link-stripped version for LLM ingestion. Links add noise to extraction context and can cause entity name pollution (e.g. `Cult_(religious_practice)` appearing as an entity).

## Pipeline Commands

All commands share common options via a callback: `--graph`, `--host`, `--port`, `--model`, `--ontology-file`. These can also be set via environment variables (`FALKORDB_GRAPH`, `FALKORDB_HOST`, `FALKORDB_PORT`, `LLM_MODEL`).

```bash
# 1. Parse HTML to Markdown (two versions)
uv run main.py parse <input_dir> <output_dir>

# 2. Discover ontology from a sample of documents
uv run main.py detect-ontology <input_dir>
# → produces ontology.json — review and edit before proceeding

# 3. Ingest documents into FalkorDB
uv run main.py ingest <input_dir>

# 4. Query the graph
uv run main.py query "Who are the siblings of Zeus?"

# 5. Interactive chat session
uv run main.py chat

# 6. Inspect relation types and frequencies
uv run main.py inspect
```

## Infrastructure

FalkorDB runs as a Docker container. The setup uses a named ACL user (not the Redis default user) via an ACL file generated from environment variables.

```bash
# Generate ACL file from .env
sh generate_acl.sh

# Start FalkorDB
docker compose up -d
```

Required `.env` variables:

```
FALKORDB_USERNAME=youruser
FALKORDB_PASSWORD=yourpassword
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
ANTHROPIC_API_KEY=sk-ant-...
```

## Extraction Boundaries

The `BOUNDARIES` string in `ontology.py` is the primary lever for extraction quality. Current version:

```
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
```

This list of forbidden derived relationships will grow as gaps are discovered. Each addition should be motivated by an observed extraction pattern, not anticipated speculatively.

## Useful Cypher Queries

```cypher
-- All parent-child relationships
MATCH (parent)-[:PARENT_OF]->(child)
RETURN parent.name, child.name

-- Sibling inference from shared parents (no SIBLING_OF needed)
MATCH (parent)-[:PARENT_OF]->(a {name: "Zeus"})
MATCH (parent)-[:PARENT_OF]->(sibling)
WHERE sibling.name <> "Zeus"
RETURN DISTINCT sibling.name

-- Grandchildren (two-hop traversal)
MATCH (a {name: "Zeus"})-[:PARENT_OF]->(child)-[:PARENT_OF]->(grandchild)
RETURN child.name, grandchild.name

-- Domain/attribute lookup
MATCH (d:Deity) WHERE d.domain CONTAINS "sea" RETURN d.name, d.domain

-- Relation type frequencies (schema inspection)
MATCH ()-[r]->()
RETURN type(r) AS relation, count(*) AS freq
ORDER BY freq DESC

-- All node labels
CALL db.labels()

-- All relationship types
CALL db.relationshipTypes()
```

## Known Issues and Observations

**Model sensitivity.** Cypher generation quality is significantly better with Claude Sonnet than Haiku. Haiku tends to generate queries that return empty results due to overly specific attribute matching or incorrect property names. For Q&A, Ollama-based local models (llama3, qwen2.5) are acceptable. For extraction and Cypher generation, a capable model is required.

**Mythological ambiguity.** Some relationships have multiple valid versions across sources (e.g. Aphrodite as daughter of Zeus in Homer vs. born from Uranus in Hesiod). The graph reflects whichever version the LLM encountered most frequently in the sampled documents. This is not a bug — it is an inherent property of a corpus-derived graph over a domain with contested facts.

**Rate limiting.** Anthropic API rate limits will be hit during ingestion of large corpora. Options: use a cheaper/faster model (Haiku), add retry logic, or migrate to local inference (see roadmap).

**graphrag_sdk Ollama support.** As of the time of writing, the SDK officially supports Ollama only for the Q&A step, not for ontology discovery or entity extraction. This may change in future SDK versions.

## Roadmap

### Short term

**Local inference for extraction.** Switch `LiteModel` to route through LiteLLM's Ollama integration (`ollama/qwen2.5:14b`) to eliminate rate limits and API cost during ingestion. Requires validating extraction quality against the Anthropic baseline on the same corpus. The model string change is a one-liner; quality validation is the work.

**Post-ingestion enrichment pass.** Add an `enrich` command that materialises derived relationships as Cypher queries run after ingestion:

```cypher
-- Example: materialise ancestor relationships transitively
MATCH (a)-[:PARENT_OF*]->(b)
WHERE NOT (a)-[:ANCESTOR_OF]->(b)
CREATE (a)-[:ANCESTOR_OF]->(b)
```

Enrichment rules are corpus-agnostic — they operate on relation type names, not content. The set of rules grows alongside the boundaries string as new derivable patterns are identified.

**Retry and progress persistence.** Long ingestion runs currently have no checkpointing. If the process fails mid-way, it restarts from scratch. A simple progress file tracking which documents have been processed would make re-runs cheap.

### Medium term

**Ontological reasoning — TBox definition.** The current ontology.json is an ABox schema (what entities and relations exist) but carries no TBox axioms (what properties those relations have). The next step is to define relation semantics explicitly:

- `PARENT_OF` is asymmetric and irreflexive
- `MARRIED_TO` is symmetric
- `PARENT_OF` composed with `PARENT_OF` implies `ANCESTOR_OF`
- Two entities sharing a `PARENT_OF` source are implicitly siblings

These axioms can be encoded as:

1. **Cypher enrichment rules** (pragmatic, already described above)
2. **SHACL constraints** over an RDF export (more principled, enables validation)
3. **OWL 2 ontology** with a reasoner like HermiT (academically correct, requires RDF triple store or export layer)

The Cypher enrichment approach is recommended first. SHACL/OWL become relevant if the rule set grows complex enough that Cypher maintenance becomes unwieldy, or if continuous reasoning (rather than batch enrichment) is required.

**Multi-source ontology alignment.** When the corpus spans multiple domains or traditions (e.g. Greek and Roman mythology, comparative religion), entity alignment becomes a problem: Zeus and Jupiter are the same entity in different traditions, but the graph may represent them as separate nodes. Approaches:

- Add `EQUIVALENT_TO` relationships during extraction (instruct the LLM to identify cross-tradition equivalences)
- Post-ingestion entity resolution pass using embedding similarity on entity names and attributes
- Explicit coreference handling in the boundaries prompt

**Staging migration to on-premises LLM.** The production target is a self-hosted Qwen 3.5 8B (or larger) for both extraction and Q&A. Recommended validation process: run the same 30-document corpus through both Anthropic and local model, compare resulting graphs using the `inspect` command and targeted Cypher queries, identify and document quality gaps before committing to the migration.

### Long term

**Vector + graph hybrid retrieval.** The current pipeline uses graph traversal exclusively for retrieval. Adding vector embeddings on chunk nodes (via `nomic-embed-text` through Ollama) enables hybrid retrieval: vector similarity finds relevant chunks, graph traversal expands context. FalkorDB supports vector indices natively. The embedding infrastructure was discussed but not implemented.

**Streaming ingestion.** For corpora significantly larger than 30 documents, batch ingestion becomes slow and expensive. A streaming approach that processes documents incrementally and updates the ontology dynamically would scale better, at the cost of ontological consistency.

**Automated ontology validation.** Before ingestion, validate that the ontology.json is internally consistent: no circular relationships, no entity types that are subsets of others, relationship domain/range constraints that make sense. Currently this is a manual review step.
