#!/usr/bin/env python

from graphrag_sdk import Ontology
from dataclasses import dataclass
import os
from collections.abc import Generator
from pathlib import Path

import typer
from typer import Argument, Typer, echo
from dotenv import load_dotenv

from graphein.html_parser import WikipediaParser
from graphein.ontology import (
    OntologyBuilder,
    GraphSession,
    sources_from_dir,
    make_model,
)

load_dotenv()
app = Typer(help="GraphRAG pipeline for FalkorDB knowledge graph reconstruction.")


@dataclass
class Config:
    graph: str
    host: str
    port: int
    model: str
    ontology_file: Path

    def load_ontology(self) -> Ontology:
        if not self.ontology_file.exists():
            typer.secho(
                f"Ontology file {self.ontology_file} not found.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        return OntologyBuilder.from_file(self.ontology_file)

    def session(self, ontology: Ontology) -> GraphSession:
        return GraphSession(
            graph_name=self.graph,
            ontology=ontology,
            model_name=self.model,
            host=self.host,
            port=self.port,
        )


@app.callback()
def common(
    ctx: typer.Context,
    graph: str = typer.Option("knowledge-graph", envvar="FALKORDB_GRAPH"),
    host: str = typer.Option("localhost", envvar="FALKORDB_HOST"),
    port: int = typer.Option(6379, envvar="FALKORDB_PORT"),
    model: str = typer.Option("claude-sonnet-4-5", envvar="LLM_MODEL"),
    ontology_file: Path = typer.Option(Path("ontology.json")),
):
    ctx.ensure_object(dict)
    ctx.obj = Config(graph, host, port, model, ontology_file)


def html_files(
    directory: Path, extension: str, recurse: bool
) -> Generator[Path, None, None]:
    for file in directory.iterdir():
        if file.is_dir():
            if not recurse:
                continue
            for f in html_files(file, extension, recurse):
                yield f

        if not str(file).endswith(f".{extension}"):
            continue

        yield file


@app.command()
def parse(
    input_dir: Path = Argument(..., help="Directory containing HTML files."),
    output_dir: Path = Argument(..., help="Directory to write markdown files."),
):
    """Parse HTML files to Markdown"""
    echo(f"Parsing HTML files from {input_dir} to {output_dir}")
    for html_file in input_dir.glob("*.html"):
        parser = WikipediaParser(html_file.read_text(encoding="utf-8"))

        out = output_dir / html_file.with_suffix(".md").name
        out.write_text(parser.to_markdown(), encoding="utf-8")

        plain_out = output_dir / html_file.with_suffix(".llm.md").name
        plain_out.write_text(parser.to_plain_markdown(), encoding="utf-8")


@app.command()
def detect_ontology(
    ctx: typer.Context,
    input_dir: Path = typer.Argument(..., help="Directory containing Markdown files."),
    sample_ratio: float = typer.Option(0.4),
    output: Path = typer.Option(Path("ontology.json")),
):
    """Discover ontology from a sample of documents and save to disk."""
    cfg: Config = ctx.obj
    model = make_model(cfg.model)
    sources = sources_from_dir(input_dir)
    n = max(3, round(len(sources) * sample_ratio))
    typer.echo(f"Discovering ontology from {n} / {len(sources)} documents...")
    ontology = OntologyBuilder.discover(sources, model, sample_ratio)
    OntologyBuilder.save(ontology, output)
    typer.echo(f"Ontology saved to {output} — review before ingesting.")


@app.command()
def ingest(
    ctx: typer.Context,
    input_dir: Path = typer.Argument(..., help="Directory containing Markdown files."),
):
    """Ingest documents into FalkorDB using a reviewed ontology."""
    cfg: Config = ctx.obj
    ontology = cfg.load_ontology()
    session = cfg.session(ontology)
    sources = sources_from_dir(input_dir)
    typer.echo(f"Ingesting {len(sources)} documents into '{cfg.graph}'...")
    session.ingest(sources)
    typer.echo("Done.")


@app.command()
def query(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="Question to ask."),
):
    """Ask a single question against the knowledge graph."""
    cfg: Config = ctx.obj
    ontology = cfg.load_ontology()
    session = cfg.session(ontology)
    typer.echo(session.query(message))


@app.command()
def chat(ctx: typer.Context):
    """Start an interactive chat session against the knowledge graph."""
    cfg: Config = ctx.obj
    ontology = cfg.load_ontology()
    session = cfg.session(ontology)
    chat_session = session.chat()
    typer.echo("Chat session started. Type 'exit' to quit.")
    while True:
        message = typer.prompt(">")
        if message.strip().lower() == "exit":
            break
        typer.echo(chat_session.send_message(message)["response"])


@app.command()
def inspect(ctx: typer.Context):
    """Print relation types and frequencies found in the graph."""
    cfg: Config = ctx.obj
    from falkordb import FalkorDB

    db = FalkorDB(
        host=cfg.host,
        port=cfg.port,
        username=os.getenv("FALKORDB_USERNAME"),
        password=os.getenv("FALKORDB_PASSWORD"),
    )
    g = db.select_graph(cfg.graph)
    result = g.query(
        "MATCH ()-[r]->() RETURN type(r) AS relation, count(*) AS freq ORDER BY freq DESC"
    )
    for row in result.result_set:
        typer.echo(f"{row[0]:<30} {row[1]}")


if __name__ == "__main__":
    app()
