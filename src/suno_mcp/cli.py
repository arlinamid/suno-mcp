"""
suno-mcp CLI — interact with Suno AI directly from the terminal.

Usage:
    suno login
    suno status
    suno generate "my lyrics" --tags "synthwave, dark" --title "Night Drive"
    suno songs
    suno download <song-id>

Run `suno --help` or `suno <command> --help` for full option lists.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

from .tools.api.tools import ApiSunoTools


def _ensure_utf8() -> None:
    """Force UTF-8 output on Windows so Rich box-drawing characters work."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
            ctypes.windll.kernel32.SetConsoleCP(65001)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Reconfigure stdout/stderr to utf-8 if possible (Python 3.11+)
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            except Exception:
                pass


_ensure_utf8()

# ─────────────────────────────────────────────
# App + shared state
# ─────────────────────────────────────────────

app = typer.Typer(
    name="suno",
    help="Suno AI CLI - generate, manage, and download music from the terminal.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

console = Console(highlight=False)
err_console = Console(stderr=True, style="bold red", highlight=False)

_tools: ApiSunoTools | None = None


def _t() -> ApiSunoTools:
    """Lazy singleton for ApiSunoTools."""
    global _tools
    if _tools is None:
        _tools = ApiSunoTools()
    return _tools


def _run(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine and return its result."""
    return asyncio.run(coro)


def _ok(msg: str) -> None:
    console.print(f"[bold green]OK[/bold green]  {msg}")


def _err(msg: str) -> None:
    err_console.print(f"ERR  {msg}")
    raise typer.Exit(1)


# ─────────────────────────────────────────────
# AUTH commands
# ─────────────────────────────────────────────

@app.command()
def login(
    headless: Annotated[bool, typer.Option("--headless", help="Run browser without a visible window")] = False,
    timeout: Annotated[int, typer.Option(help="Seconds to wait for login")] = 120,
) -> None:
    """
    [bold]Open a browser window and log in to Suno.[/bold]

    Captures ALL session cookies (including HTTP-only tokens) and saves
    them encrypted to your OS keychain. Auto-refresh works for months.
    """
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as p:
        p.add_task("Opening browser…")
        result = _run(_t().browser_login(headless=headless, timeout=timeout))
    console.print(result)


@app.command()
def status(
    json_out: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Show current session status, token expiry, and credit balance."""
    session_result = _run(_t().session_info())
    try:
        credits_result = _run(_t().get_credits())
    except Exception:
        credits_result = "(not authenticated)"

    if json_out:
        console.print_json(json.dumps({"session": session_result, "credits": credits_result}))
        return

    console.print(Panel(session_result, title="[bold cyan]Session[/bold cyan]", expand=False))
    console.print(Panel(credits_result, title="[bold cyan]Credits[/bold cyan]", expand=False))


@app.command()
def refresh(
    force: Annotated[bool, typer.Option("--force", help="Refresh even if token is still valid")] = False,
) -> None:
    """Force-refresh the Clerk JWT token without re-logging in."""
    result = _run(_t().refresh_session(force=force))
    console.print(result)


@app.command("clear-auth")
def clear_auth() -> None:
    """Delete all stored credentials from the OS keychain."""
    confirm = typer.confirm("This will delete all saved Suno credentials. Continue?")
    if not confirm:
        raise typer.Abort()
    result = _run(_t().clear_credentials())
    _ok(result)


# ─────────────────────────────────────────────
# GENERATE commands
# ─────────────────────────────────────────────

@app.command()
def generate(
    prompt: Annotated[str, typer.Argument(help="Lyrics or auto-mode description")],
    tags: Annotated[str, typer.Option("--tags", "-t", help="Style tags (<=200 chars)")] = "",
    title: Annotated[str, typer.Option("--title", help="Song title")] = "",
    model: Annotated[str, typer.Option("--model", "-m", help="Model alias: v5, v4.5x, v4, v3.5")] = "v5",
    vocal_gender: Annotated[str, typer.Option("--gender", help="Vocal gender: male, female, or empty")] = "",
    weirdness: Annotated[int, typer.Option("--weirdness", "-w", min=0, max=100, help="0=conventional 100=experimental")] = 50,
    style_weight: Annotated[int, typer.Option("--style-weight", min=0, max=100, help="Style tag influence")] = 50,
    negative_tags: Annotated[str, typer.Option("--no", help="Styles to avoid")] = "",
    instrumental: Annotated[bool, typer.Option("--instrumental", help="No vocals")] = False,
    wait: Annotated[bool, typer.Option("--wait", help="Wait for audio URL before returning")] = False,
    download_to: Annotated[Optional[Path], typer.Option("--download", "-d", help="Download MP3 to this directory after generation")] = None,
) -> None:
    """
    [bold]Generate a new song (2 variations).[/bold]

    Examples:

        suno generate "rainy nights, neon streets" --tags "synthwave, female vocals" --title "Neon Rain" --wait

        suno generate "[Verse]\\nLine one\\nLine two\\n[Chorus]\\nHook here" --tags "folk pop, acoustic" --gender female --weirdness 20 --download ~/Music
    """
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as p:
        p.add_task("Submitting generation (browser window will open ~15s)…")
        result = _run(_t().api_generate_track(
            prompt=prompt,
            tags=tags,
            title=title,
            model=model,
            vocal_gender=vocal_gender or None,
            weirdness=weirdness,
            style_weight=style_weight,
            negative_tags=negative_tags,
            make_instrumental=instrumental,
        ))

    console.print(result)

    # Extract song IDs for --wait / --download
    import re
    ids = re.findall(r"ID\s+:\s+([0-9a-f-]{36})", result)

    if (wait or download_to) and ids:
        for song_id in ids:
            with Progress(SpinnerColumn(), TextColumn(f"Waiting for {song_id[:8]}…"), transient=True) as p:
                p.add_task("")
                song_result = _run(_t().wait_for_song(song_id=song_id, timeout=180))
            console.print(song_result)

            if download_to:
                with Progress(SpinnerColumn(), TextColumn(f"Downloading {song_id[:8]}…"), transient=True) as p:
                    p.add_task("")
                    dl_result = _run(_t().download_song(song_id=song_id, output_dir=str(download_to)))
                _ok(dl_result)


@app.command()
def wait(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
    timeout: Annotated[int, typer.Option(help="Seconds to wait")] = 120,
) -> None:
    """Poll until a song finishes generating, then show its audio URL."""
    with Progress(SpinnerColumn(), TextColumn(f"Waiting for [cyan]{song_id[:8]}…[/cyan]"), transient=True) as p:
        p.add_task("")
        result = _run(_t().wait_for_song(song_id=song_id, timeout=timeout))
    console.print(result)


@app.command()
def extend(
    song_id: Annotated[str, typer.Argument(help="Song UUID to extend")],
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Additional lyrics or style")] = "",
    tags: Annotated[str, typer.Option("--tags", "-t", help="Style tags for extension")] = "",
    continue_at: Annotated[float, typer.Option("--at", help="Timestamp in seconds to branch from (0 = end)")] = 0,
    model: Annotated[str, typer.Option("--model", "-m")] = "v5",
) -> None:
    """Continue generating from where an existing song ends."""
    result = _run(_t().extend_song(
        song_id=song_id,
        prompt=prompt,
        tags=tags,
        continue_at=continue_at,
        model=model,
    ))
    console.print(result)


@app.command()
def remix(
    song_id: Annotated[str, typer.Argument(help="Song UUID to remix")],
    prompt: Annotated[str, typer.Argument(help="New style description or lyrics")],
    tags: Annotated[str, typer.Option("--tags", "-t", help="New style tags")] = "",
    title: Annotated[str, typer.Option("--title", help="Title for the remix")] = "",
    model: Annotated[str, typer.Option("--model", "-m")] = "v5",
) -> None:
    """Remix an existing song with a new style or direction."""
    result = _run(_t().remix_song(
        song_id=song_id,
        prompt=prompt,
        tags=tags,
        title=title,
        model=model,
    ))
    console.print(result)


# ─────────────────────────────────────────────
# LIBRARY commands
# ─────────────────────────────────────────────

@app.command()
def songs(
    page: Annotated[int, typer.Option("--page", "-p", help="Page number (0-based)")] = 0,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List your personal song library."""
    result = _run(_t().get_my_songs(page=page))
    if json_out:
        console.print_json(result if result.startswith("{") or result.startswith("[") else json.dumps({"result": result}))
    else:
        console.print(result)


@app.command()
def song(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Get full details for a single song."""
    result = _run(_t().get_song(song_id=song_id))
    if json_out:
        console.print_json(result if result.startswith("{") else json.dumps({"result": result}))
    else:
        console.print(result)


@app.command()
def trending(
    period: Annotated[str, typer.Option("--period", help="Time period: day, week, or empty (all-time)")] = "",
    page: Annotated[int, typer.Option("--page", "-p")] = 0,
) -> None:
    """Show trending songs on Suno."""
    result = _run(_t().get_trending_songs(page=page, period=period))
    console.print(result)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    search_type: Annotated[str, typer.Option("--type", help="audio, playlist, or user")] = "audio",
    page: Annotated[int, typer.Option("--page", "-p")] = 0,
) -> None:
    """Search public Suno songs, playlists, or users."""
    result = _run(_t().search(query=query, search_type=search_type, page=page))
    console.print(result)


@app.command()
def liked(
    page: Annotated[int, typer.Option("--page", "-p")] = 0,
) -> None:
    """List songs you have liked."""
    result = _run(_t().get_liked_songs(page=page))
    console.print(result)


# ─────────────────────────────────────────────
# PLAYLIST commands
# ─────────────────────────────────────────────

@app.command()
def playlists() -> None:
    """List your playlists."""
    result = _run(_t().get_my_playlists())
    console.print(result)


@app.command()
def playlist(
    playlist_id: Annotated[str, typer.Argument(help="Playlist UUID")],
    page: Annotated[int, typer.Option("--page", "-p")] = 0,
) -> None:
    """Show songs inside a playlist."""
    result = _run(_t().get_playlist(playlist_id=playlist_id, page=page))
    console.print(result)


@app.command("playlist-create")
def playlist_create(
    name: Annotated[str, typer.Argument(help="Playlist name")],
    description: Annotated[str, typer.Option("--desc", help="Playlist description")] = "",
) -> None:
    """Create a new playlist."""
    result = _run(_t().create_playlist(name=name, description=description))
    _ok(result)


@app.command("playlist-add")
def playlist_add(
    playlist_id: Annotated[str, typer.Argument(help="Playlist UUID")],
    song_id: Annotated[str, typer.Argument(help="Song UUID to add")],
) -> None:
    """Add a song to a playlist."""
    result = _run(_t().add_to_playlist(playlist_id=playlist_id, song_id=song_id))
    _ok(result)


@app.command("playlist-remove")
def playlist_remove(
    playlist_id: Annotated[str, typer.Argument(help="Playlist UUID")],
    song_id: Annotated[str, typer.Argument(help="Song UUID to remove")],
) -> None:
    """Remove a song from a playlist."""
    result = _run(_t().remove_from_playlist(playlist_id=playlist_id, song_id=song_id))
    _ok(result)


# ─────────────────────────────────────────────
# DOWNLOAD commands
# ─────────────────────────────────────────────

@app.command()
def download(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Directory to save files")] = Path.home() / "Music" / "suno-downloads",
    no_cover: Annotated[bool, typer.Option("--no-cover", help="Skip cover art download")] = False,
) -> None:
    """Download a song's MP3 (and optional cover art) to a local directory."""
    output.mkdir(parents=True, exist_ok=True)
    with Progress(SpinnerColumn(), TextColumn(f"Downloading [cyan]{song_id[:8]}…[/cyan]"), transient=True) as p:
        p.add_task("")
        result = _run(_t().download_song(
            song_id=song_id,
            output_dir=str(output),
            include_cover=not no_cover,
        ))
    _ok(result)


@app.command("download-playlist")
def download_playlist(
    playlist_id: Annotated[str, typer.Argument(help="Playlist UUID")],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path.home() / "Music" / "suno-downloads",
    max_songs: Annotated[int, typer.Option("--max", help="Maximum songs to download")] = 50,
) -> None:
    """Download all songs in a playlist."""
    output.mkdir(parents=True, exist_ok=True)
    with Progress(SpinnerColumn(), TextColumn("Downloading playlist…"), transient=True) as p:
        p.add_task("")
        result = _run(_t().download_playlist(
            playlist_id=playlist_id,
            output_dir=str(output),
            max_songs=max_songs,
        ))
    console.print(result)


@app.command("download-library")
def download_library(
    output: Annotated[Path, typer.Option("--output", "-o")] = Path.home() / "Music" / "suno-downloads" / "my-songs",
    page: Annotated[int, typer.Option("--page", "-p")] = 0,
    max_songs: Annotated[int, typer.Option("--max")] = 20,
) -> None:
    """Download a page of songs from your personal library."""
    output.mkdir(parents=True, exist_ok=True)
    with Progress(SpinnerColumn(), TextColumn("Downloading library…"), transient=True) as p:
        p.add_task("")
        result = _run(_t().download_my_songs(
            output_dir=str(output),
            page=page,
            max_songs=max_songs,
        ))
    console.print(result)


# ─────────────────────────────────────────────
# SONG ACTION commands
# ─────────────────────────────────────────────

@app.command()
def like(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
) -> None:
    """Like / upvote a song."""
    result = _run(_t().like_song(song_id=song_id))
    _ok(result)


@app.command()
def publish(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
) -> None:
    """Make one of your songs publicly visible."""
    result = _run(_t().make_public(song_id=song_id))
    _ok(result)


@app.command()
def delete(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
) -> None:
    """Move a song to trash (soft delete)."""
    confirm = typer.confirm(f"Move song {song_id[:8]}… to trash?")
    if not confirm:
        raise typer.Abort()
    result = _run(_t().delete_song(song_id=song_id))
    _ok(result)


# ─────────────────────────────────────────────
# ACCOUNT commands
# ─────────────────────────────────────────────

@app.command()
def credits() -> None:
    """Show remaining credits and subscription plan."""
    result = _run(_t().get_credits())
    console.print(Panel(result, title="[bold cyan]Suno Credits[/bold cyan]", expand=False))


@app.command()
def contests() -> None:
    """List currently active Suno song contests."""
    result = _run(_t().get_contests())
    console.print(result)


@app.command()
def plans() -> None:
    """Show available Suno subscription plans and pricing."""
    result = _run(_t().get_subscription_plans())
    console.print(result)


# ─────────────────────────────────────────────
# ADVANCED commands
# ─────────────────────────────────────────────

@app.command()
def lyrics(
    prompt: Annotated[str, typer.Argument(help="Topic or mood for lyric generation")],
) -> None:
    """Generate AI-written lyrics from a topic (no audio — text only)."""
    with Progress(SpinnerColumn(), TextColumn("Generating lyrics…"), transient=True) as p:
        p.add_task("")
        result = _run(_t().generate_lyrics(prompt=prompt))
    console.print(Panel(result, title="[bold cyan]Generated Lyrics[/bold cyan]"))


@app.command()
def stems(
    song_id: Annotated[str, typer.Argument(help="Song UUID to separate")],
) -> None:
    """Split a completed song into individual stem tracks (requires Premier)."""
    result = _run(_t().generate_stems(song_id=song_id))
    console.print(result)


@app.command()
def concat(
    clip_id: Annotated[str, typer.Argument(help="Extension clip ID to merge with its parent")],
) -> None:
    """Merge an extension clip with its parent into a full-length song."""
    result = _run(_t().concat_song(clip_id=clip_id))
    console.print(result)


# ─────────────────────────────────────────────
# HELP / INFO command
# ─────────────────────────────────────────────

@app.command()
def info() -> None:
    """Show a quick reference of all commands."""
    table = Table(
        title="suno CLI - command reference",
        box=box.ASCII_DOUBLE_HEAD,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Command", style="bold white", no_wrap=True)
    table.add_column("Description")
    table.add_column("Key options")

    rows = [
        # Auth
        ("login",             "Browser login — saves session to keychain",       "--headless"),
        ("status",            "Session + credit balance",                         "--json"),
        ("refresh",           "Force-refresh the JWT token",                      "--force"),
        ("clear-auth",        "Delete all stored credentials",                    ""),
        # Generate
        ("generate <prompt>", "Generate a song (2 variations)",                   "--tags --title --model --wait --download"),
        ("wait <id>",         "Poll until song audio is ready",                   "--timeout"),
        ("extend <id>",       "Continue generating from where a song ends",       "--prompt --at"),
        ("remix <id> <desc>", "Remix a song with a new style",                    "--tags --title"),
        ("lyrics <topic>",    "Generate lyrics text (no audio)",                  ""),
        # Library
        ("songs",             "List your song library",                           "--page"),
        ("song <id>",         "Details for a single song",                        "--json"),
        ("trending",          "Trending songs feed",                              "--period day|week"),
        ("search <query>",    "Search public songs/playlists/users",              "--type"),
        ("liked",             "Songs you have liked",                             "--page"),
        # Playlists
        ("playlists",         "List your playlists",                              ""),
        ("playlist <id>",     "Songs inside a playlist",                          "--page"),
        ("playlist-create",   "Create a new playlist",                            "--desc"),
        ("playlist-add",      "Add a song to a playlist",                         ""),
        ("playlist-remove",   "Remove a song from a playlist",                    ""),
        # Download
        ("download <id>",     "Download MP3 + cover art",                         "--output --no-cover"),
        ("download-playlist", "Download all songs in a playlist",                 "--output --max"),
        ("download-library",  "Bulk download personal library",                   "--output --page --max"),
        # Actions
        ("like <id>",         "Like a song",                                      ""),
        ("publish <id>",      "Make a song public",                               ""),
        ("delete <id>",       "Move song to trash",                               ""),
        # Account
        ("credits",           "Remaining credits + subscription plan",            ""),
        ("contests",          "Active song contests",                             ""),
        ("plans",             "Available subscription plans",                     ""),
        # Advanced
        ("stems <id>",        "Split song into stem tracks (Premier)",            ""),
        ("concat <clip-id>",  "Merge extension clip with parent",                 ""),
    ]

    section_headers = {"login", "generate <prompt>", "songs", "playlists", "download <id>", "like <id>", "credits", "stems <id>"}
    section_labels = {
        "login":             "AUTH",
        "generate <prompt>": "GENERATE",
        "songs":             "LIBRARY",
        "playlists":         "PLAYLISTS",
        "download <id>":     "DOWNLOAD",
        "like <id>":         "SONG ACTIONS",
        "credits":           "ACCOUNT",
        "stems <id>":        "ADVANCED",
    }

    for cmd, desc, opts in rows:
        if cmd in section_headers:
            table.add_section()
            label = section_labels[cmd]
            table.add_row(f"[dim]-- {label} --[/dim]", "", "", style="dim")
        table.add_row(cmd, desc, f"[dim]{opts}[/dim]")

    console.print(table)
    console.print("\n[dim]Run [bold]suno <command> --help[/bold] for detailed options.[/dim]")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main() -> None:
    app()


if __name__ == "__main__":
    main()
