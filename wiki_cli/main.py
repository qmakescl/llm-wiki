"""wiki — LLM-maintained personal research knowledge base."""

import click
from pathlib import Path
from rich.console import Console

console = Console()

WIKI_ROOT_ENV = "WIKI_ROOT"


def _apply_saved_config() -> None:
    """~/.config/llm-wiki/config.json 이 있으면 환경변수에 적용."""
    try:
        from wiki_web import config as _cfg
        _cfg.apply_env(_cfg.load())
    except Exception:
        pass


def find_wiki_root(start: Path = Path.cwd()) -> Path:
    """Walk up from cwd looking for AGENTS.md (wiki root marker).

    Falls back to the active domain from config.json when cwd-based search fails,
    so CLI works naturally after a wiki was created from the web UI.
    """
    for parent in [start, *start.parents]:
        if (parent / "AGENTS.md").exists():
            return parent
    try:
        from wiki_web import config as _cfg
        candidate = _cfg.get_wiki_root()
        if (candidate / "AGENTS.md").exists():
            return candidate
    except Exception:
        pass
    raise click.ClickException(
        "No AGENTS.md found. Run 'wiki init' to create a new wiki, "
        "or cd into an existing wiki directory."
    )


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """LLM-maintained personal research wiki.

    Commands:\n
      init     Create a new wiki in the current directory\n
      ingest   Add a source document to the wiki\n
      query    Ask a question against the wiki\n
      lint     Health-check the wiki for issues\n
    """
    ctx.ensure_object(dict)
    _apply_saved_config()


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--model", "-m", default=None, help="LLM model override (e.g. gpt-4o)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--metrics-output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write ingest timing/call metrics to a JSON file",
)
def ingest(path: str, model: str | None, yes: bool, metrics_output: Path | None) -> None:
    """Add a source document to the wiki.

    PATH is the file to ingest (PDF, markdown, or text).
    The file should live inside the raw/ directory.
    """
    from wiki_cli.ops.ingest import run_ingest
    from wiki_cli.metrics import Metrics

    wiki_root = find_wiki_root()
    source = Path(path).resolve()

    if not yes:
        console.print(f"[bold]Wiki root:[/bold] {wiki_root}")
        console.print(f"[bold]Source:   [/bold] {source}")
        click.confirm("Proceed with ingest?", abort=True)

    metrics = Metrics() if metrics_output else None
    if metrics:
        with metrics.timer("ingest.total"):
            run_ingest(wiki_root=wiki_root, source=source, model=model, metrics=metrics)
        metrics.write_json(metrics_output)
        console.print(f"[dim]Metrics written: {metrics_output}[/dim]")
    else:
        run_ingest(wiki_root=wiki_root, source=source, model=model)


@cli.command()
@click.argument("question", nargs=-1, required=True)
@click.option("--model", "-m", default=None, help="LLM model override")
@click.option("--save", "-s", is_flag=True, help="Save answer to synthesis/")
def query(question: tuple[str, ...], model: str | None, save: bool) -> None:
    """Ask a question against the wiki.

    QUESTION is the natural language query (quote if multi-word).

    Examples:\n
      wiki query "What is attention mechanism?"\n
      wiki query "Compare BERT and GPT" --save\n
    """
    from wiki_cli.ops.query import run_query

    wiki_root = find_wiki_root()
    q = " ".join(question)
    run_query(wiki_root=wiki_root, question=q, model=model, save=save)


@cli.command()
@click.option("--model", "-m", default=None, help="LLM model override")
@click.option("--fix", is_flag=True, help="Attempt auto-fix of simple issues")
def lint(model: str | None, fix: bool) -> None:
    """Health-check the wiki for issues.

    Looks for: contradictions, orphan pages, missing cross-references,
    stale content, and TODO markers.
    """
    from wiki_cli.ops.lint import run_lint

    wiki_root = find_wiki_root()
    run_lint(wiki_root=wiki_root, model=model, auto_fix=fix)


@cli.group()
def vector() -> None:
    """Manage the local chunk vector index."""


@vector.command("rebuild")
def vector_rebuild() -> None:
    """Rebuild vector chunks for all wiki pages."""
    from wiki_cli import vector_index

    wiki_root = find_wiki_root()
    stats = vector_index.refresh_all(wiki_root)
    console.print(
        f"[green]✓[/green] Vector index rebuilt: "
        f"{stats.pages_indexed} pages, {stats.chunks_indexed} chunks"
    )
    if stats.errors:
        console.print(f"[yellow]Warnings:[/yellow] {stats.errors} page(s) failed or skipped")


@vector.command("stats")
def vector_stats() -> None:
    """Show vector index stats."""
    from wiki_cli import vector_index

    wiki_root = find_wiki_root()
    info = vector_index.stats(wiki_root)
    console.print(f"[bold]Vector DB:[/bold] {info['path']}")
    console.print(f"Pages : {info['pages']}")
    console.print(f"Chunks: {info['chunks']}")


@vector.command("clear")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def vector_clear(yes: bool) -> None:
    """Delete the local vector index database."""
    from wiki_cli import vector_index

    wiki_root = find_wiki_root()
    if not yes:
        click.confirm(f"Delete vector index under {wiki_root / '.vectors'}?", abort=True)
    vector_index.clear(wiki_root)
    console.print("[green]✓[/green] Vector index cleared")


@cli.command()
@click.argument("directory", default=".", type=click.Path())
@click.option("--domain", "-d", prompt="Wiki domain (e.g. 'deep learning research')",
              help="Topic domain for this wiki")
def init(directory: str, domain: str) -> None:
    """Create a new wiki in DIRECTORY (default: current directory).

    Creates wiki/ and data/ subdirectories under DIRECTORY.
    """
    from wiki_cli.ops.init import run_init

    base = Path(directory).resolve()
    wiki_root = base / "wiki"
    data_root = base / "data"
    run_init(wiki_root=wiki_root, data_root=data_root, domain=domain)

    try:
        from wiki_web import config as _cfg
        import re as _re
        folder = _re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-") or "my-wiki"
        cfg_data = _cfg.load()
        cfg_data["workspace_root"] = str(base)
        _cfg.save(cfg_data)
        new_domain = _cfg.add_domain(name=domain, folder=folder)
        _cfg.switch_domain(new_domain["id"])
        console.print(f"[dim]Config: domain '{domain}' registered (id={new_domain['id']})[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: could not register in config.json — {e}[/yellow]")
