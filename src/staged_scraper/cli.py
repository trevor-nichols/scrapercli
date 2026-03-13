from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from .config import DEFAULT_CONFIG, ConfigError, load_config
from .models import DocumentResult, ExtractionAttempt, Scope
from .runtime import RuntimeFactory
from .version import __version__


app = typer.Typer(
    name="staged-scraper",
    help="HTTP-first staged website-to-Markdown scraper with auditable escalation.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()
error_console = Console(stderr=True)


def _build_config(
    *,
    config_path: Path | None,
    output_dir: Path | None,
    browser_mode: str,
    auto_interact_mode: str,
    timeout_seconds: float | None,
    rate_limit: float | None,
    max_pages: int | None,
) -> tuple[Any, dict[str, Any]]:
    overrides: dict[str, Any] = {}
    if browser_mode != "auto":
        overrides.setdefault("browser", {})["enabled"] = browser_mode == "on"
    if auto_interact_mode != "auto":
        overrides.setdefault("browser", {})["auto_interact"] = auto_interact_mode == "on"
    if timeout_seconds is not None:
        overrides["timeout_seconds"] = timeout_seconds
    if rate_limit is not None:
        overrides.setdefault("rate_limit", {})["requests_per_second"] = rate_limit
    if max_pages is not None:
        overrides.setdefault("crawl", {})["max_pages"] = max_pages

    try:
        config = load_config(config_path, overrides=overrides or None)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if output_dir is not None:
        config.output.root_dir = output_dir
    return config, overrides


def _print_attempts(attempts: list[ExtractionAttempt]) -> None:
    table = Table(title="Extraction attempts")
    table.add_column("Mode")
    table.add_column("Success")
    table.add_column("Outcome")
    table.add_column("Quality")
    table.add_column("Signals")
    table.add_column("Elapsed ms", justify="right")
    for attempt in attempts:
        quality = "n/a"
        if attempt.quality is not None:
            quality = "pass" if attempt.quality.passed else ", ".join(attempt.quality.reasons) or "pass"
        table.add_row(
            attempt.mode.value,
            "yes" if attempt.success else "no",
            attempt.outcome,
            quality,
            ", ".join(attempt.observed_signals[:6]),
            str(attempt.elapsed_ms),
        )
    console.print(table)


def _print_result_summary(result: DocumentResult) -> None:
    summary = Table(title="Result summary", show_header=False)
    summary.add_column("Field")
    summary.add_column("Value")
    summary.add_row("Requested URL", result.requested_url)
    summary.add_row("Normalized URL", result.normalized_url)
    summary.add_row("Final URL", result.final_url or "")
    summary.add_row("Success", "yes" if result.success else "no")
    selected_mode = result.attempts[-1].mode.value if result.attempts else ""
    if result.document is not None:
        for attempt in reversed(result.attempts):
            if attempt.document is result.document:
                selected_mode = attempt.mode.value
                break
    summary.add_row("Selected mode", selected_mode)
    summary.add_row("Markdown path", str(result.markdown_path) if result.markdown_path else "")
    summary.add_row("Metadata path", str(result.metadata_path) if result.metadata_path else "")
    summary.add_row("Decisions log", str(result.decisions_path) if result.decisions_path else "")
    if result.errors:
        summary.add_row("Errors", "; ".join(result.errors))
    console.print(summary)


def _emit_json(payload: dict[str, Any]) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False, default=str))


@app.command()
def scrape(
    url: str = typer.Argument(..., help="Target page URL."),
    scope: Scope = typer.Option(Scope.PAGE, "--scope", help="Extraction scope."),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False, file_okay=True, readable=True, help="YAML config file."),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False, dir_okay=True, help="Output directory root."),
    browser: str = typer.Option("auto", "--browser", help="Browser mode: auto, on, off."),
    auto_interact: str = typer.Option("auto", "--auto-interact", help="Auto interaction mode: auto, on, off."),
    timeout_seconds: float | None = typer.Option(None, "--timeout-seconds", min=1.0, help="HTTP timeout override."),
    rate_limit: float | None = typer.Option(None, "--rate-limit", min=0.0, help="Requests per second override."),
    stdout_markdown: bool = typer.Option(False, "--stdout", help="Print resulting Markdown to stdout."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON summary."),
) -> None:
    browser = browser.lower().strip()
    auto_interact = auto_interact.lower().strip()
    if browser not in {"auto", "on", "off"}:
        raise typer.BadParameter("--browser must be one of: auto, on, off")
    if auto_interact not in {"auto", "on", "off"}:
        raise typer.BadParameter("--auto-interact must be one of: auto, on, off")

    cfg, _ = _build_config(
        config_path=config,
        output_dir=output_dir,
        browser_mode=browser,
        auto_interact_mode=auto_interact,
        timeout_seconds=timeout_seconds,
        rate_limit=rate_limit,
        max_pages=None,
    )
    runtime = RuntimeFactory.build(cfg)
    try:
        result = runtime.orchestrator.scrape(url, scope)
        result_path = runtime.artifacts.save_json_document("result.json", result.model_dump(mode="json"))
        if json_output:
            payload = result.model_dump(mode="json")
            payload["summary_path"] = str(result_path)
            _emit_json(payload)
        else:
            _print_result_summary(result)
            if result.attempts:
                _print_attempts(result.attempts)
            console.print(f"Result JSON: {result_path}")
            if stdout_markdown and result.document is not None:
                console.print(result.document.markdown)
        raise typer.Exit(code=0 if result.success else 2)
    finally:
        runtime.close()


@app.command()
def crawl(
    url: str = typer.Argument(..., help="Root URL to crawl."),
    scope: Scope = typer.Option(Scope.SECTION, "--scope", help="Crawl scope."),
    max_pages: int = typer.Option(25, "--max-pages", min=1, help="Maximum number of pages to crawl."),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False, file_okay=True, readable=True, help="YAML config file."),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False, dir_okay=True, help="Output directory root."),
    browser: str = typer.Option("auto", "--browser", help="Browser mode: auto, on, off."),
    auto_interact: str = typer.Option("auto", "--auto-interact", help="Auto interaction mode: auto, on, off."),
    timeout_seconds: float | None = typer.Option(None, "--timeout-seconds", min=1.0, help="HTTP timeout override."),
    rate_limit: float | None = typer.Option(None, "--rate-limit", min=0.0, help="Requests per second override."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON summary."),
) -> None:
    browser = browser.lower().strip()
    auto_interact = auto_interact.lower().strip()
    if browser not in {"auto", "on", "off"}:
        raise typer.BadParameter("--browser must be one of: auto, on, off")
    if auto_interact not in {"auto", "on", "off"}:
        raise typer.BadParameter("--auto-interact must be one of: auto, on, off")

    cfg, _ = _build_config(
        config_path=config,
        output_dir=output_dir,
        browser_mode=browser,
        auto_interact_mode=auto_interact,
        timeout_seconds=timeout_seconds,
        rate_limit=rate_limit,
        max_pages=max_pages,
    )
    runtime = RuntimeFactory.build(cfg)
    try:
        manifest = runtime.crawler.crawl(url, scope, max_pages)
        manifest_path = runtime.artifacts.save_json_document("crawl_manifest.json", manifest.model_dump(mode="json"))
        if json_output:
            payload = manifest.model_dump(mode="json")
            payload["manifest_path"] = str(manifest_path)
            _emit_json(payload)
        else:
            summary = Table(title="Crawl summary")
            summary.add_column("URL")
            summary.add_column("Success")
            summary.add_column("Mode")
            summary.add_column("Markdown")
            for entry in manifest.entries:
                summary.add_row(
                    entry.url,
                    "yes" if entry.success else "no",
                    entry.extraction_mode.value if entry.extraction_mode else "",
                    entry.markdown_path or "",
                )
            console.print(summary)
            console.print(f"Manifest: {manifest_path}")
        failed = any(not entry.success for entry in manifest.entries)
        raise typer.Exit(code=2 if failed else 0)
    finally:
        runtime.close()


@app.command()
def inspect(
    url: str = typer.Argument(..., help="URL to inspect without running the full extraction pipeline."),
    scope: Scope = typer.Option(Scope.PAGE, "--scope", help="Inspection scope."),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False, file_okay=True, readable=True, help="YAML config file."),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False, dir_okay=True, help="Output directory root."),
    browser: str = typer.Option("auto", "--browser", help="Browser mode: auto, on, off."),
    auto_interact: str = typer.Option("auto", "--auto-interact", help="Auto interaction mode: auto, on, off."),
    timeout_seconds: float | None = typer.Option(None, "--timeout-seconds", min=1.0, help="HTTP timeout override."),
    rate_limit: float | None = typer.Option(None, "--rate-limit", min=0.0, help="Requests per second override."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON summary."),
) -> None:
    browser = browser.lower().strip()
    auto_interact = auto_interact.lower().strip()
    if browser not in {"auto", "on", "off"}:
        raise typer.BadParameter("--browser must be one of: auto, on, off")
    if auto_interact not in {"auto", "on", "off"}:
        raise typer.BadParameter("--auto-interact must be one of: auto, on, off")

    cfg, _ = _build_config(
        config_path=config,
        output_dir=output_dir,
        browser_mode=browser,
        auto_interact_mode=auto_interact,
        timeout_seconds=timeout_seconds,
        rate_limit=rate_limit,
        max_pages=None,
    )
    runtime = RuntimeFactory.build(cfg)
    try:
        bundle = runtime.discovery.discover(url, scope)
        bundle_path = runtime.artifacts.save_json_document("discovery_bundle.json", bundle.model_dump(mode="json"))
        if json_output:
            payload = bundle.model_dump(mode="json")
            payload["bundle_path"] = str(bundle_path)
            _emit_json(payload)
            return

        overview = Table(title="Discovery overview", show_header=False)
        overview.add_column("Field")
        overview.add_column("Value")
        overview.add_row("Requested URL", bundle.requested_url)
        overview.add_row("Normalized URL", bundle.normalized_url)
        overview.add_row("Framework", bundle.framework_hint.framework_family.value)
        overview.add_row("Framework confidence", f"{bundle.framework_hint.confidence_score:.2f}")
        overview.add_row("Signals", ", ".join(bundle.signals))
        overview.add_row("Robots", bundle.robots.url if bundle.robots else "")
        overview.add_row("LLMS hits", str(len(bundle.llms_snapshots)))
        overview.add_row("Discovery JSON", str(bundle_path))
        console.print(overview)

        if bundle.framework_hint.evidence:
            console.print(f"Framework evidence: {', '.join(bundle.framework_hint.evidence)}")

        candidates = Table(title="Ranked candidate sources")
        candidates.add_column("#", justify="right")
        candidates.add_column("Kind")
        candidates.add_column("Confidence", justify="right")
        candidates.add_column("Cost", justify="right")
        candidates.add_column("URL")
        candidates.add_column("Evidence")
        for idx, candidate in enumerate(bundle.candidates, start=1):
            candidates.add_row(
                str(idx),
                candidate.kind.value,
                f"{candidate.confidence:.2f}",
                str(candidate.cost),
                candidate.url or "",
                ", ".join(candidate.evidence[:4]),
            )
        console.print(candidates)
    finally:
        runtime.close()


@app.command("init-config")
def init_config(
    path: Path = typer.Argument(..., help="Destination YAML path for a starter config."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    if path.exists() and not force:
        raise typer.BadParameter(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = DEFAULT_CONFIG.model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(f"Wrote starter config to {path}")


@app.command()
def version() -> None:
    console.print(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
