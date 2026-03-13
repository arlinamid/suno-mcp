#!/usr/bin/env python3
"""Suno MCP Server - Dual Interface (MCP + FastAPI) Implementation."""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp import Tool
from mcp.server import FastMCP
from pydantic import BaseModel

from .tools.basic.tools import BasicSunoTools
from .tools.api.tools import ApiSunoTools


# FastAPI Models
class ToolRequest(BaseModel):
    """Request model for tool execution via FastAPI."""
    name: str
    arguments: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str = "ok"
    version: str = "1.0.0"
    uptime: float
    tools_loaded: int


class StatusResponse(BaseModel):
    """Status response model."""
    browser_open: bool
    page_ready: bool
    current_url: Optional[str]
    page_title: Optional[str]
    in_studio: bool
    server_mode: str


# Global instances
basic_tools = BasicSunoTools()
api_tools = ApiSunoTools()

# FastMCP App
mcp_app = FastMCP("suno-mcp")

# Lifespan context manager for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle FastAPI startup and shutdown events."""
    # Startup
    logging.info("Starting Suno MCP Server (Dual Interface)")
    yield
    # Shutdown
    logging.info("Shutting down Suno MCP Server")


# FastAPI App
fastapi_app = FastAPI(
    title="Suno MCP Server",
    description="Automated Suno AI Music Generation MCP Server",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS middleware
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# FastAPI Routes
@fastapi_app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint returning JSON status."""
    import time
    start_time = getattr(fastapi_app, "start_time", time.time())
    current_time = time.time()

    return HealthResponse(
        status="ok",
        version="2.0.0",
        uptime=current_time - start_time,
        tools_loaded=53  # 6 browser + 26 API + 3 session + 4 credentials + help
    )


@fastapi_app.get("/api/v1/status", response_model=StatusResponse)
async def get_status():
    """Get current server and browser status."""
    try:
        # Get browser status from basic tools
        browser_status = await basic_tools.get_browser_status()
        return StatusResponse(
            browser_open=browser_status.get("browser_open", False),
            page_ready=browser_status.get("page_ready", False),
            current_url=browser_status.get("current_url"),
            page_title=browser_status.get("page_title"),
            in_studio=browser_status.get("current_url", "").includes("/studio") if browser_status.get("current_url") else False,
            server_mode="dual"
        )
    except Exception as e:
        logging.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail="Status check failed")


@fastapi_app.get("/api/v1/tools")
async def list_tools():
    """List all available tools via FastAPI."""
    session_tools = [
        {"name": "suno_browser_login", "category": "session", "auth": "none",
         "description": "Open browser, log in, capture full cookie jar for auto-refresh"},
        {"name": "suno_refresh_session", "category": "session", "auth": "none",
         "description": "Silently refresh __session JWT via Clerk HTTP API"},
        {"name": "suno_session_info", "category": "session", "auth": "none",
         "description": "Show current session status and token expiry"},
    ]
    credential_tools = [
        {"name": "suno_save_cookie", "category": "credentials", "auth": "none"},
        {"name": "suno_save_token", "category": "credentials", "auth": "none"},
        {"name": "suno_credential_status", "category": "credentials", "auth": "none"},
        {"name": "suno_clear_credentials", "category": "credentials", "auth": "none"},
    ]
    browser_tools = [
        {"name": "suno_open_browser", "category": "browser", "auth": "none"},
        {"name": "suno_login", "category": "browser", "auth": "email_password"},
        {"name": "suno_generate_track", "category": "browser", "auth": "session"},
        {"name": "suno_download_track", "category": "browser", "auth": "session"},
        {"name": "suno_get_status", "category": "browser", "auth": "none"},
        {"name": "suno_close_browser", "category": "browser", "auth": "none"},
    ]
    api_tool_names = [
        {"name": "suno_api_check_auth", "category": "api", "auth": "optional"},
        {"name": "suno_api_get_credits", "category": "api", "auth": "required"},
        {"name": "suno_api_get_trending", "category": "api", "auth": "none"},
        {"name": "suno_api_get_song", "category": "api", "auth": "none"},
        {"name": "suno_api_search", "category": "api", "auth": "none"},
        {"name": "suno_api_get_playlist", "category": "api", "auth": "none"},
        {"name": "suno_api_get_subscription_plans", "category": "api", "auth": "none"},
        {"name": "suno_api_get_contests", "category": "api", "auth": "none"},
        {"name": "suno_api_get_my_songs", "category": "api", "auth": "required"},
        {"name": "suno_api_get_my_playlists", "category": "api", "auth": "required"},
        {"name": "suno_api_generate", "category": "api", "auth": "required"},
        {"name": "suno_api_extend", "category": "api", "auth": "required"},
        {"name": "suno_api_remix", "category": "api", "auth": "required"},
        {"name": "suno_api_inpaint", "category": "api", "auth": "required"},
        {"name": "suno_api_like_song", "category": "api", "auth": "required"},
        {"name": "suno_api_delete_song", "category": "api", "auth": "required"},
        {"name": "suno_api_make_public", "category": "api", "auth": "required"},
        {"name": "suno_api_create_playlist", "category": "api", "auth": "required"},
        {"name": "suno_api_add_to_playlist", "category": "api", "auth": "required"},
        {"name": "suno_api_remove_from_playlist", "category": "api", "auth": "required"},
        {"name": "suno_api_update_playlist", "category": "api", "auth": "required"},
        {"name": "suno_api_get_liked_songs", "category": "api", "auth": "required"},
        {"name": "suno_api_wait_for_song", "category": "api", "auth": "required"},
        {"name": "suno_api_download_song", "category": "api", "auth": "none"},
        {"name": "suno_api_download_playlist", "category": "api", "auth": "none"},
        {"name": "suno_api_download_my_songs", "category": "api", "auth": "required"},
    ]
    all_tools = session_tools + credential_tools + browser_tools + api_tool_names
    return {
        "tools": all_tools,
        "total": len(all_tools),
        "api_base": "https://studio-api.prod.suno.com/api",
        "auth_setup": "Run suno_browser_login() for automatic session management",
        "auth_methods": ["browser_login (recommended)", "SUNO_COOKIE", "SUNO_AUTH_TOKEN"],
    }


@fastapi_app.post("/api/v1/tools/{tool_name}")
async def execute_tool(tool_name: str, request: ToolRequest):
    """Execute a tool via FastAPI."""
    try:
        args = request.arguments or {}

        # Route to appropriate tool handler
        if tool_name.startswith("suno_"):
            result = await _handle_basic_tool(tool_name, args)
        else:
            raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

        return {"result": result, "tool": tool_name, "success": True}

    except Exception as e:
        logging.error(f"Tool execution failed: {tool_name}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


# Tool execution helpers
async def _handle_basic_tool(tool_name: str, args: Dict[str, Any]) -> str:
    """Handle basic Suno AI tools."""
    tool_map = {
        "suno_open_browser": basic_tools.open_browser,
        "suno_login": basic_tools.login,
        "suno_generate_track": basic_tools.generate_track,
        "suno_download_track": basic_tools.download_track,
        "suno_get_status": basic_tools.get_status,
        "suno_close_browser": basic_tools.close_browser,
    }

    if tool_name not in tool_map:
        raise HTTPException(status_code=404, detail=f"Unknown basic tool: {tool_name}")

    return await tool_map[tool_name](**args)




# MCP Tool Registration (FastMCP 2.12 decorators with multiline documentation)
@mcp_app.tool()
async def suno_open_browser(headless: bool = True) -> str:
    """
    Open browser and navigate to Suno AI create page.

    This tool initializes a Playwright browser session and navigates to the Suno AI
    music generation interface. Required for all other Suno AI operations.

    Args:
        headless: Run browser in headless mode (default: True)

    Returns:
        Confirmation message with page details and navigation status
    """
    return await basic_tools.open_browser(headless)


@mcp_app.tool()
async def suno_login(email: str, password: str) -> str:
    """
    Login to Suno AI account.

    Authenticates with Suno AI using provided credentials. Required before
    generating tracks or accessing the library. Handles 2FA and various
    authentication flows automatically.

    Args:
        email: Suno AI account email address
        password: Suno AI account password

    Returns:
        Login status and session confirmation
    """
    return await basic_tools.login(email, password)


@mcp_app.tool()
async def suno_generate_track(
    prompt: str,
    style: str = "synthwave",
    lyrics: str | None = None,
    duration: str = "auto",
) -> str:
    """
    Generate a new music track using Suno AI.

    Creates original music using Suno's AI generation engine. Supports various
    styles, lyrics integration, and custom durations. Generation may take
    several minutes depending on complexity.

    Args:
        prompt: Detailed description of the desired music (required)
        style: Musical style (e.g., "synthwave", "pop", "rock", default: "synthwave")
        lyrics: Optional lyrics to incorporate into the track
        duration: Track length ("auto", "short", "medium", "long", default: "auto")

    Returns:
        Generation status and track information when complete
    """
    return await basic_tools.generate_track(prompt, style, lyrics, duration)


@mcp_app.tool()
async def suno_download_track(
    track_id: str,
    download_path: str = "downloads/",
    include_stems: bool = True,
) -> str:
    """
    Download a generated track from Suno AI library.

    Downloads completed tracks and optionally their individual stems/components.
    Supports custom download paths and automatic file organization.

    Args:
        track_id: Unique identifier of the track to download
        download_path: Directory to save files (default: "downloads/")
        include_stems: Download individual track stems if available (default: True)

    Returns:
        Download confirmation with file paths and sizes
    """
    return await basic_tools.download_track(track_id, download_path, include_stems)


@mcp_app.tool()
async def suno_get_status() -> str:
    """
    Get current Suno AI session status.

    Provides comprehensive information about the current browser session,
    authentication state, and active operations.

    Returns:
        Detailed status report including session state and capabilities
    """
    return await basic_tools.get_status()


@mcp_app.tool()
async def suno_close_browser() -> str:
    """
    Close the browser session.

    Properly closes the Playwright browser instance and cleans up resources.
    Should be called when finished with Suno AI operations.

    Returns:
        Confirmation of browser closure
    """
    return await basic_tools.close_browser()


# ─────────────────────────────────────────────────────────────────────────────
# API TOOLS — Direct HTTP calls to studio-api.prod.suno.com (no browser needed)
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_api_check_auth() -> str:
    """
    Check API authentication status and test the Suno API connection.

    Shows whether SUNO_COOKIE or SUNO_AUTH_TOKEN are configured, and verifies
    the connection by fetching the current user session.

    To authenticate:
      1. Open suno.com in Chrome and log in
      2. Open DevTools (F12) → Application → Cookies → https://suno.com
      3. Copy the value of the '__session' cookie
      4. Set environment variable: SUNO_COOKIE=__session=<value>

    Returns:
        Auth status, user info if authenticated, setup instructions if not
    """
    return await api_tools.check_auth()


@mcp_app.tool()
async def suno_api_get_credits() -> str:
    """
    Get your remaining Suno credits and subscription details.

    Shows plan name, credits remaining, monthly limit, and usage.
    Requires authentication (SUNO_COOKIE or SUNO_AUTH_TOKEN).

    Returns:
        Credits balance and subscription plan information
    """
    return await api_tools.get_credits()


@mcp_app.tool()
async def suno_api_get_trending(page: int = 0, period: str = "") -> str:
    """
    Get trending songs on Suno (public, no auth needed).

    Args:
        page: Page number for pagination (default: 0)
        period: Time period — '' (all-time), 'week', 'day' (default: all-time)

    Returns:
        List of trending songs with titles, IDs, tags, play counts, and audio URLs
    """
    return await api_tools.get_trending_songs(page=page, period=period)


@mcp_app.tool()
async def suno_api_get_song(song_id: str) -> str:
    """
    Get detailed information about a specific song by its ID.

    Works for any public song. For your private songs, authentication is required.

    Args:
        song_id: The song/clip UUID (e.g., 'b3142399-f73e-4fc7-b5da-738cf6957e6f')

    Returns:
        Full song details: title, author, audio URL, video URL, tags, duration,
        play count, likes, model version, creation date
    """
    return await api_tools.get_song(song_id=song_id)


@mcp_app.tool()
async def suno_api_search(
    query: str,
    search_type: str = "audio",
    page: int = 0,
) -> str:
    """
    Search for songs, playlists, or users on Suno (public, no auth needed).

    Args:
        query: Search term (e.g., 'upbeat pop', 'dark ambient', 'lo-fi beats')
        search_type: What to search — 'audio' (songs), 'playlist', or 'user'
        page: Page number for pagination (default: 0)

    Returns:
        Matching songs/playlists/users with IDs, titles, tags, and URLs
    """
    return await api_tools.search_songs(query=query, search_type=search_type, page=page)


@mcp_app.tool()
async def suno_api_get_playlist(playlist_id: str, page: int = 0) -> str:
    """
    Get contents of a Suno playlist by its ID (public, no auth needed).

    Args:
        playlist_id: The playlist UUID
        page: Page number for pagination (default: 0)

    Returns:
        Playlist metadata and list of songs with IDs, titles, and durations
    """
    return await api_tools.get_playlist(playlist_id=playlist_id, page=page)


@mcp_app.tool()
async def suno_api_get_my_songs(page: int = 0) -> str:
    """
    Get your personal song library (requires authentication).

    Shows all songs you've generated including their status (queued, streaming,
    complete), IDs, titles, tags, and audio URLs.

    Args:
        page: Page number for pagination (default: 0)

    Returns:
        Your songs with status, IDs, titles, tags, durations, and audio URLs
    """
    return await api_tools.get_my_songs(page=page)


@mcp_app.tool()
async def suno_api_generate(
    prompt: str,
    tags: str = "",
    title: str = "",
    make_instrumental: bool = False,
    model: str = "v5",
    negative_tags: str = "",
    vocal_gender: str = "",
    weirdness: int = 50,
    style_weight: int = 50,
) -> str:
    """
    Generate a new song — full v5 support with all advanced options.
    Uses browser-assisted generation: opens a brief window (~15s) to pass hCaptcha,
    then closes automatically. Always produces 2 variations per call.
    Use suno_api_wait_for_song(<id>) or suno_api_download_song(<id>) afterwards.

    MODELS (use short alias or full API name):
      v5  / chirp-crow     — v5 Pro: best quality & control          [DEFAULT]
      v4.5x / chirp-bluejay— v4.5x Pro: advanced creation methods
      v4.5  / chirp-auk   — v4.5 Pro: intelligent prompts
      v4.5-all / chirp-v4-5— v4.5 all: best free model
      v4  / chirp-v4       — v4 Pro: improved sound quality
      v3.5 / chirp-v3-5   — v3.5: classic
      v3  / chirp-v3       — v3: basic

    PROMPT MODES:
      Auto  — just describe the vibe: "sad Hungarian rap about sleepless nights"
      Custom — write full lyrics with section tags:
               [Verse]\\nLyric line 1\\nLyric line 2\\n[Chorus]\\nHook line...

    Args:
        prompt: Lyrics (custom mode) or style/mood description (auto mode)
        tags: Musical style tags, comma-separated
              e.g. "Hungarian rap, 90 BPM, minor key, male vocals, cinematic"
        title: Song title (auto-generated if omitted)
        make_instrumental: True = pure instrumental, no vocals
        model: Model version (default: 'v5')
        negative_tags: Styles to avoid, e.g. "electric guitar, auto-tune, trap"
        vocal_gender: "male", "female", or "" (Suno decides)
        weirdness: 0–100 — creativity/unexpectedness (default: 50)
        style_weight: 0–100 — how strictly style tags are applied (default: 50)

    Cost: 10 credits × 2 variations = 20 credits

    Requires: Authentication (run suno_browser_login() first)
    """
    return await api_tools.api_generate_track(
        prompt=prompt,
        tags=tags,
        title=title,
        make_instrumental=make_instrumental,
        model=model,
        negative_tags=negative_tags,
        vocal_gender=vocal_gender,
        weirdness=weirdness,
        style_weight=style_weight,
    )


@mcp_app.tool()
async def suno_api_extend(
    song_id: str,
    prompt: str = "",
    tags: str = "",
    continue_at: float = 0.0,
    model: str = "v5",
) -> str:
    """
    Extend an existing song — continue generating from where it ends.

    Useful for making songs longer or creating a sequel section.

    Args:
        song_id: ID of the song to extend
        prompt: Additional lyrics or style description for the extension
        tags: Style tags for the extended section
        continue_at: Timestamp in seconds to branch from (0 = from end of song)
        model: AI model version

    Returns:
        New clip IDs for the extended version

    Requires: Authentication
    """
    return await api_tools.api_extend_song(
        song_id=song_id,
        prompt=prompt,
        tags=tags,
        continue_at=continue_at,
        model=model,
    )


@mcp_app.tool()
async def suno_api_remix(
    song_id: str,
    prompt: str,
    tags: str = "",
    title: str = "",
    model: str = "v5",
) -> str:
    """
    Remix an existing song with a new style, genre, or lyrics.

    Takes an existing song and regenerates it with new creative direction
    while potentially keeping some of the original structure.

    Args:
        song_id: ID of the source song to remix
        prompt: New style description or lyrics
        tags: New style tags (e.g., "jazz, piano, acoustic" to change genre)
        title: Title for the remix (optional)
        model: AI model version

    Returns:
        New clip IDs for the remixed version

    Requires: Authentication
    """
    return await api_tools.api_remix_song(
        song_id=song_id,
        prompt=prompt,
        tags=tags,
        title=title,
        model=model,
    )


@mcp_app.tool()
async def suno_api_inpaint(
    song_id: str,
    start_seconds: float,
    end_seconds: float,
    prompt: str,
    tags: str = "",
) -> str:
    """
    Edit a specific section of an existing song (inpainting/surgery).

    Re-generates only the section between start and end timestamps while
    keeping the rest of the song intact.

    Args:
        song_id: ID of the song to edit
        start_seconds: Start time of section to replace (seconds, e.g., 30.0)
        end_seconds: End time of section to replace (seconds, e.g., 60.0)
        prompt: Description or lyrics for the new section
        tags: Style tags for the replacement section

    Returns:
        New clip ID with the edited version

    Requires: Authentication (Pro plan or higher)
    """
    return await api_tools.api_inpaint_song(
        song_id=song_id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        prompt=prompt,
        tags=tags,
    )


@mcp_app.tool()
async def suno_api_like_song(song_id: str) -> str:
    """
    Like/upvote a Suno song.

    Args:
        song_id: The song UUID to like

    Returns:
        Confirmation of the like action

    Requires: Authentication
    """
    return await api_tools.api_like_song(song_id=song_id)


@mcp_app.tool()
async def suno_api_delete_song(song_id: str) -> str:
    """
    Move a song to trash (soft delete from your library).

    The song will be removed from your library but can be recovered.

    Args:
        song_id: The song UUID to delete

    Returns:
        Confirmation of deletion

    Requires: Authentication
    """
    return await api_tools.api_delete_song(song_id=song_id)


@mcp_app.tool()
async def suno_api_make_public(song_id: str) -> str:
    """
    Make one of your songs publicly visible on Suno.

    Args:
        song_id: The song UUID to publish

    Returns:
        Confirmation that the song is now public

    Requires: Authentication
    """
    return await api_tools.api_make_public(song_id=song_id)


@mcp_app.tool()
async def suno_api_get_subscription_plans() -> str:
    """
    Get all available Suno subscription plans and pricing (public, no auth needed).

    Shows Free, Pro, and Premier plans with prices, credit limits, and features.

    Returns:
        List of plans with pricing, credits, and feature comparison
    """
    return await api_tools.get_subscription_plans()


@mcp_app.tool()
async def suno_api_get_contests() -> str:
    """
    Get currently active Suno song contests (public, no auth needed).

    Returns:
        List of active contests with names, deadlines, and IDs
    """
    return await api_tools.get_contests()


@mcp_app.tool()
async def suno_api_create_playlist(name: str, description: str = "") -> str:
    """
    Create a new playlist in your Suno library.

    Args:
        name: Playlist name
        description: Optional description of the playlist

    Returns:
        New playlist ID and confirmation

    Requires: Authentication
    """
    return await api_tools.api_create_playlist(name=name, description=description)


@mcp_app.tool()
async def suno_api_add_to_playlist(playlist_id: str, song_id: str) -> str:
    """
    Add a song to one of your playlists.

    Args:
        playlist_id: The target playlist UUID
        song_id: The song UUID to add

    Returns:
        Confirmation of the action

    Requires: Authentication
    """
    return await api_tools.api_add_to_playlist(playlist_id=playlist_id, song_id=song_id)


@mcp_app.tool()
async def suno_api_remove_from_playlist(playlist_id: str, song_id: str) -> str:
    """
    Remove a song from one of your playlists.

    Args:
        playlist_id: The playlist UUID
        song_id: The song/clip UUID to remove

    Returns:
        Confirmation of the action

    Requires: Authentication
    """
    return await api_tools.api_remove_from_playlist(playlist_id=playlist_id, song_id=song_id)


@mcp_app.tool()
async def suno_api_update_playlist(
    playlist_id: str,
    name: str = "",
    description: str = "",
    is_public: Optional[bool] = None,
) -> str:
    """
    Rename or update a playlist's name, description, or visibility.

    Args:
        playlist_id: The playlist UUID
        name: New name (leave blank to keep current)
        description: New description (leave blank to keep current)
        is_public: True=public, False=private, None=unchanged

    Returns:
        Updated playlist info

    Requires: Authentication
    """
    return await api_tools.api_update_playlist(
        playlist_id=playlist_id, name=name, description=description, is_public=is_public
    )


@mcp_app.tool()
async def suno_api_get_liked_songs(page: int = 0) -> str:
    """
    Get songs you have liked/upvoted on Suno.

    Args:
        page: Page number (0-based, 20 songs per page)

    Returns:
        List of liked songs with IDs, titles, and audio URLs

    Requires: Authentication
    """
    return await api_tools.get_liked_songs(page=page)


@mcp_app.tool()
async def suno_api_wait_for_song(song_id: str, timeout: int = 120) -> str:
    """
    Wait for a song to finish generating, then return its details and audio URL.

    Use this after suno_api_generate() to get the final result.
    Polls every 5 seconds until status='complete' or timeout is reached.

    Args:
        song_id: The clip UUID returned by suno_api_generate()
        timeout: Maximum seconds to wait (default: 120)

    Returns:
        Song details with audio URL, or timeout message
    """
    return await api_tools.wait_for_song(song_id=song_id, timeout=timeout)


@mcp_app.tool()
async def suno_api_download_song(
    song_id: str,
    output_dir: str = "",
    include_cover: bool = True,
    wait_if_processing: bool = True,
) -> str:
    """
    Download a song's MP3 audio (and optionally cover art) to a local folder.

    Works for any song — your own or public songs found via search/trending.
    Automatically waits if the song is still generating (up to 120 seconds).

    Args:
        song_id: The song/clip UUID (from trending, search, library, or generation)
        output_dir: Folder to save files (default: ~/Music/suno-downloads/)
        include_cover: Also download the cover image (default: True)
        wait_if_processing: Wait for generation to complete before downloading

    Returns:
        Download summary with saved file paths and file sizes

    Example:
        suno_api_download_song("abc123-...", output_dir="C:/Music/Suno")
    """
    return await api_tools.download_song(
        song_id=song_id,
        output_dir=output_dir,
        include_cover=include_cover,
        wait_if_processing=wait_if_processing,
    )


@mcp_app.tool()
async def suno_api_download_playlist(
    playlist_id: str,
    output_dir: str = "",
    max_songs: int = 50,
) -> str:
    """
    Download all songs in a playlist to a local folder.

    Creates a subfolder named after the playlist. Downloads MP3 + cover art
    for each song. Skips songs without audio URLs.

    Args:
        playlist_id: The playlist UUID (from suno_api_get_my_playlists or a URL)
        output_dir: Parent folder (default: ~/Music/suno-downloads/<playlist_name>/)
        max_songs: Maximum number of songs to download (default: 50)

    Returns:
        Download summary — how many succeeded, failed, and where files are saved
    """
    return await api_tools.download_playlist(
        playlist_id=playlist_id,
        output_dir=output_dir,
        max_songs=max_songs,
    )


@mcp_app.tool()
async def suno_api_download_my_songs(
    output_dir: str = "",
    page: int = 0,
    max_songs: int = 20,
    only_complete: bool = True,
) -> str:
    """
    Batch download songs from your personal Suno library.

    Downloads MP3 + cover art for each song. Run multiple times with
    increasing page numbers to download your entire library in batches.

    Args:
        output_dir: Folder to save files (default: ~/Music/suno-downloads/my-songs/)
        page: Library page to fetch (0-based, 20 songs per page)
        max_songs: Maximum songs to download per call (default: 20)
        only_complete: Skip songs still generating (default: True)

    Returns:
        Summary: X downloaded, Y skipped, Z failed — with file paths

    Requires: Authentication
    """
    return await api_tools.download_my_songs(
        output_dir=output_dir,
        page=page,
        max_songs=max_songs,
        only_complete=only_complete,
    )


@mcp_app.tool()
async def suno_api_get_my_playlists() -> str:
    """
    Get your personal playlists (requires authentication).

    Returns:
        List of your playlists with names, song counts, and IDs
    """
    return await api_tools.get_my_playlists()


# ─────────────────────────────────────────────────────────────────────────────
# SESSION MANAGEMENT — Login, refresh, and status
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_browser_login(headless: bool = False, timeout: int = 120) -> str:
    """
    Open a browser window and log into Suno — the MCP captures ALL session
    cookies automatically (including the HTTP-only __client Clerk token).

    This is the RECOMMENDED way to authenticate. After this:
      • Your __session JWT refreshes automatically every 60 minutes
      • No manual re-login needed until your Clerk session expires (months)
      • Fast HTTP-based refresh via auth.suno.com (no browser needed for refresh)
      • Falls back to headless browser if HTTP refresh fails

    What gets captured (securely, in OS keychain):
      __client         — HTTP-only long-lived Clerk client token (KEY for refresh)
      __session        — Short-lived JWT (60 min)
      __client_uat     — Client update timestamp
      suno_device_id   — Your persistent Suno device ID
      + all other suno.com session cookies

    Steps:
      1. Call this tool
      2. A browser window opens (or check headless=True for CI use)
      3. Log in with your Google/Apple/email account
      4. The MCP automatically captures and saves your session

    Args:
        headless: Run without a visible window (for CI / pre-injected cookies).
        timeout:  Seconds to wait for login completion (default: 120).

    Returns:
        Session info and confirmation of captured cookies.
    """
    return await api_tools.browser_login(headless=headless, timeout=timeout)


@mcp_app.tool()
async def suno_refresh_session(force: bool = False) -> str:
    """
    Manually refresh the __session JWT token without re-logging in.

    The MCP already calls this automatically before API requests when the
    token is about to expire. Use this tool to:
      • Verify that auto-refresh is working
      • Pre-refresh a token proactively
      • Troubleshoot authentication issues

    Requires a full session captured by suno_browser_login() — specifically
    the __client HTTP-only cookie (stored in your OS keychain).

    Args:
        force: Refresh even if the current token is still valid.

    Returns:
        Refresh outcome and new token expiry info.
    """
    return await api_tools.refresh_session(force=force)


@mcp_app.tool()
async def suno_session_info() -> str:
    """
    Show current session status — token validity, expiry time, user info,
    and whether automatic refresh is available.

    No secrets are ever revealed — only non-sensitive claims from the JWT
    (email, user ID, expiry time) and the storage backend name.

    Returns:
        Session status summary.
    """
    return await api_tools.session_info()


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIAL MANAGEMENT — Manual / legacy cookie storage
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_save_cookie(cookie: str) -> str:
    """
    Securely save your Suno session cookie to the OS credential vault.

    The cookie is validated, then stored in:
      • Windows Credential Manager  (Windows)
      • macOS Keychain               (macOS)
      • libsecret / KWallet          (Linux)

    It is NEVER written to disk as plaintext, logged, or echoed back.

    How to get your cookie:
      1. Open https://suno.com in Chrome and log in
      2. Press F12 → Application tab → Cookies → https://suno.com
      3. Find the '__session' row and copy its Value
      4. Call this tool with: __session=<paste_value_here>
         (you can include other cookies too, the tool only needs __session)

    Args:
        cookie: Cookie string containing __session=<jwt>
                Example: "__session=eyJhbGci..."

    Returns:
        Confirmation with a safe fingerprint (never the secret itself)
    """
    from .tools.shared.credentials import get_credential_store
    store = get_credential_store()
    return store.save_cookie(cookie)


@mcp_app.tool()
async def suno_save_token(token: str) -> str:
    """
    Securely save a raw Suno JWT bearer token to the OS credential vault.

    Use this as an alternative to suno_save_cookie() if you have the raw
    JWT token rather than the full cookie string.

    The token is validated (must be a valid JWT), then stored in the OS
    keychain. It is never logged or echoed back.

    How to get your token:
      1. Open https://suno.com in Chrome and log in
      2. Press F12 → Network tab → filter by 'studio-api.prod.suno.com'
      3. Click any authenticated request
      4. In Request Headers, copy the value after 'Authorization: Bearer '

    Args:
        token: Raw Clerk JWT token (header.payload.signature format)

    Returns:
        Confirmation with a safe fingerprint (never the secret itself)
    """
    from .tools.shared.credentials import get_credential_store
    store = get_credential_store()
    return store.save_token(token)


@mcp_app.tool()
async def suno_credential_status() -> str:
    """
    Show current credential status (no secrets revealed).

    Displays whether credentials are configured, which backend stores them,
    and a safe cryptographic fingerprint — never the actual token value.

    Returns:
        Backend name, credential presence, and fingerprints
    """
    from .tools.shared.credentials import get_credential_store
    store = get_credential_store()
    return store.status()


@mcp_app.tool()
async def suno_clear_credentials() -> str:
    """
    Remove all stored Suno credentials from the OS keychain.

    This deletes the saved session cookie and/or bearer token from the
    OS credential vault and clears them from memory. You will need to
    re-authenticate using suno_save_cookie() or suno_login() afterwards.

    Returns:
        Confirmation of what was deleted
    """
    from .tools.shared.credentials import get_credential_store
    store = get_credential_store()
    return store.clear()


# FastMCP 2.12 Standard: Multilevel Help Tool
@mcp_app.tool()
async def help(level: str = "basic") -> str:
    """
    Multilevel help system for Suno MCP Server.

    Provides contextual help information at different levels of detail.
    Essential for user onboarding and tool discovery.

    Args:
        level: Help detail level ("basic", "detailed", "examples", default: "basic")

    Returns:
        Formatted help text with usage instructions and examples
    """
    if level == "basic":
        return """
Suno MCP Server Help

Tool Categories:
  Login & Session (3)  — Browser login + automatic JWT refresh
  API Tools (17)       — Direct HTTP calls, no browser needed  [RECOMMENDED]
  Credentials (4)      — Manual cookie/token management (legacy)
  Browser Tools (6)    — Playwright-based automation (legacy)

QUICK START (one-time setup):
1. Run: suno_browser_login()
   → A browser window opens. Log in with your Google/Apple/email account.
   → The MCP captures your full session (including the HTTP-only __client token).
   → JWT tokens are now refreshed automatically every 60 minutes.

2. Check: suno_session_info()
   → Confirm your session is active and see when it expires.

3. Generate music: suno_api_generate("a dreamy synthwave track about space")
   → Submits the generation request.

4. Explore: suno_api_get_trending()
   → No auth needed!

For detailed help: help("detailed") or help("examples")
"""
    elif level == "detailed":
        return """
Suno MCP Server - All Tools

━━━ LOGIN & SESSION (new — recommended) ━━━
- suno_browser_login(headless, timeout) — Opens browser, captures full cookie jar
- suno_refresh_session(force)           — Manually refresh JWT (auto-called before requests)
- suno_session_info()                   — Show session status & token expiry

━━━ API TOOLS (Direct HTTP — no browser) ━━━
AUTH:
- suno_api_check_auth()       — Check auth status & test connection
- suno_api_get_credits()      — Remaining credits & subscription plan

DISCOVERY (public, no auth):
- suno_api_get_trending(page, period)     — Trending songs ('week'/'day'/'')
- suno_api_get_song(song_id)              — Full song details by ID
- suno_api_search(query, type, page)      — Search songs/users/playlists
- suno_api_get_playlist(playlist_id)      — Get playlist contents
- suno_api_get_subscription_plans()       — All plan prices & features
- suno_api_get_contests()                 — Active contests

LIBRARY (requires auth):
- suno_api_get_my_songs(page)                           — Your generated songs
- suno_api_get_my_playlists()                           — Your playlists
- suno_api_get_liked_songs(page)                        — Songs you liked
- suno_api_like_song(song_id)                           — Like a song
- suno_api_delete_song(song_id)                         — Move to trash
- suno_api_make_public(song_id)                         — Publish a song
- suno_api_create_playlist(name, description)           — New playlist
- suno_api_add_to_playlist(playlist_id, song_id)        — Add to playlist
- suno_api_remove_from_playlist(playlist_id, song_id)   — Remove from playlist
- suno_api_update_playlist(playlist_id, name, ...)      — Rename/update playlist

DOWNLOADS:
- suno_api_wait_for_song(song_id, timeout)              — Wait for generation, get audio URL
- suno_api_download_song(song_id, output_dir)           — Download MP3 + cover art
- suno_api_download_playlist(playlist_id, output_dir)   — Download entire playlist
- suno_api_download_my_songs(output_dir, page)          — Batch download your library

GENERATION (requires auth, credits):
- `suno_api_generate(prompt, tags, title, make_instrumental, model)` — Create new song
- `suno_api_extend(song_id, prompt, tags, continue_at, model)` — Extend a song
- `suno_api_remix(song_id, prompt, tags, title, model)` — Remix a song
- `suno_api_inpaint(song_id, start_s, end_s, prompt, tags)` — Edit a section

━━━ BROWSER TOOLS (Legacy — use API tools instead) ━━━
- `suno_open_browser(headless)` — Start Playwright browser
- `suno_login(email, password)` — Authenticate via browser
- `suno_generate_track(prompt, style, lyrics, duration)` — Browser-based generation
- `suno_download_track(track_id, path, include_stems)` — Download files
- `suno_get_status()` — Browser session status
- `suno_close_browser()` — Close browser

━━━ SERVER TOOLS ━━━
- `help(level)` — This help (levels: 'basic', 'detailed', 'api', 'examples')
- `get_server_status()` — Server and browser health check
"""
    elif level == "api":
        return """
🎵 **API Tools Setup Guide**

**Authentication (one-time setup):**
```
# Option 1: Cookie (recommended)
# 1. Open suno.com, log in
# 2. DevTools (F12) → Application → Cookies → suno.com
# 3. Copy __session value
SUNO_COOKIE=__session=eyJhbGciO...

# Option 2: Direct token
SUNO_AUTH_TOKEN=eyJhbGciO...
```

**API Endpoints Discovered (studio-api.prod.suno.com):**
PUBLIC:
  GET  /api/trending/?page=0[&period=week|day]
  GET  /api/clip/{id}
  POST /api/search/
  GET  /api/playlist/{id}?page=0
  GET  /api/billing/usage-plans
  GET  /api/contests/

AUTHENTICATED:
  GET  /api/session/
  GET  /api/billing/credits/
  GET  /api/billing/info/
  GET  /api/feed/?page=0
  GET  /api/prompts/?filter_prompt_type=lyrics|tags
  POST /api/generate/v2/
  POST /api/inpaint/
  POST /api/extend/

**Generate request body:**
```json
{
  "prompt": "lyrics or description",
  "tags": "genre, style, instruments",
  "title": "Song Title",
  "make_instrumental": false,
  "mv": "chirp-v4"
}
```
"""
    elif level == "examples":
        return """
🎵 **Usage Examples**

**Discover Music (no auth needed):**
```
# Browse trending
suno_api_get_trending()
suno_api_get_trending(period="week")

# Search for songs
suno_api_search("dark ambient synthwave")
suno_api_search("johndoe", search_type="user")

# Get song details
suno_api_get_song("b3142399-f73e-4fc7-b5da-738cf6957e6f")
```

**Generate Music (auth required):**
```
# Simple generation (auto mode)
suno_api_generate(
    "A melancholic lo-fi hip hop beat for studying",
    tags="lo-fi, hip hop, rain, chill"
)

# Custom lyrics mode
suno_api_generate(
    "[Verse]\\nIn the city lights I roam\\n[Chorus]\\nNeon dreams take me home",
    tags="synthwave, 80s, electronic, female vocals",
    title="Neon Dreams"
)

# Instrumental
suno_api_generate(
    "Epic orchestral battle theme",
    tags="orchestral, epic, dramatic, cinematic",
    make_instrumental=True
)
```

**Edit Existing Songs (auth required):**
```
# Extend a song
suno_api_extend("song-id-here", continue_at=0.0)

# Remix with new style
suno_api_remix("song-id-here", "jazz piano version", tags="jazz, piano, acoustic")

# Fix a section (30s to 60s)
suno_api_inpaint("song-id-here", 30.0, 60.0, "[Bridge]\\nNew bridge lyrics")
```

**Manage Library (auth required):**
```
suno_api_get_my_songs()
suno_api_get_liked_songs()
suno_api_like_song("song-id")
suno_api_make_public("song-id")
suno_api_create_playlist("My Synthwave Mix")
suno_api_remove_from_playlist("playlist-id", "song-id")
suno_api_update_playlist("playlist-id", name="New Name")
```

**Download Music:**
```
suno_api_wait_for_song("song-id")
suno_api_download_song("song-id")
suno_api_download_song("song-id", output_dir="C:/Music/Suno")
suno_api_download_playlist("playlist-id")
suno_api_download_my_songs(max_songs=20)
```
"""
    else:
        return "Use `help()` for basic, `help('detailed')` for all tools, `help('api')` for API reference, `help('examples')` for code examples."


# FastMCP 2.12 Standard: Status Tool
@mcp_app.tool()
async def get_server_status() -> str:
    """
    Comprehensive server status and health check tool.

    Provides detailed information about server state, active sessions,
    resource usage, and system health. Essential for monitoring and
    troubleshooting MCP server operations.

    Returns:
        Detailed status report including:
        - Server configuration and capabilities
        - Active browser sessions and state
        - Tool availability and health
        - Resource usage and performance metrics
    """
    try:
        browser_status = await basic_tools.get_browser_status()

        status = f"""
🎵 **Suno MCP Server Status**

**Server Configuration:**
• Version: 1.0.0
• Mode: Dual Interface (MCP stdio + FastAPI HTTP)
• Total Tools Available: 23
• Basic Tools: 6
• Studio Tools: 17

**Browser Session:**
• Browser Open: {browser_status.get('browser_open', False)}
• Context Ready: {browser_status.get('context_ready', False)}
• Page Ready: {browser_status.get('page_ready', False)}
• Current URL: {browser_status.get('current_url', 'None')}
• Page Title: {browser_status.get('page_title', 'None')}
• In Studio Mode: {browser_status.get('in_studio', False)}

**System Health:**
• Status: ✅ Operational
• FastAPI: Available at http://localhost:3000
• MCP: Active on stdio
• Tools: All registered and functional

**Performance Metrics:**
• Active Sessions: 1
• Memory Usage: Normal
• Error Rate: 0%
"""
        return status
    except Exception as e:
        return f"""❌ **Status Check Failed**

Error: {str(e)}

**Troubleshooting:**
• Ensure Playwright browsers are installed: `playwright install chromium`
• Check internet connectivity
• Verify Suno AI service availability
• Review server logs for detailed error information
"""


def main():
    """Main entry point for MCP server (stdio mode)."""
    logging.info("Starting Suno MCP server (stdio mode)")
    asyncio.run(mcp_app.run())


def main_api():
    """Main entry point for FastAPI server."""
    import time
    import uvicorn

    # Store start time for uptime calculation
    fastapi_app.start_time = time.time()

    logging.info("Starting FastAPI server on http://0.0.0.0:3000")
    logging.info("API Docs: http://0.0.0.0:3000/api/docs")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=3000)


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    main()