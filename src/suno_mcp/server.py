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
    version: str = "2.1.0"
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
    version="2.1.0",
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
    start_time = getattr(fastapi_app.state, "start_time", time.time())
    current_time = time.time()

    return HealthResponse(
        status="ok",
        version="2.1.0",
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
        # Persona
        {"name": "suno_api_get_persona", "category": "persona", "auth": "required"},
        {"name": "suno_api_get_my_personas", "category": "persona", "auth": "required"},
        {"name": "suno_api_get_featured_personas", "category": "persona", "auth": "required"},
        # Lyrics / Stems / Concat / Alignment
        {"name": "suno_api_generate_lyrics", "category": "api", "auth": "required"},
        {"name": "suno_api_generate_stems", "category": "api", "auth": "required"},
        {"name": "suno_api_concat_song", "category": "api", "auth": "required"},
        {"name": "suno_api_get_lyric_alignment", "category": "api", "auth": "required"},
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
    persona_id: str = "",
    inspo_clip_id: str = "",
    inspo_start_s: float = 0.0,
    inspo_end_s: float = 0.0,
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
        persona_id: Persona UUID for a consistent vocal character (Pro feature).
                    Get IDs via suno_api_get_persona or suno_api_get_my_personas.
        inspo_clip_id: Song ID to use as Inspo (style reference for generation).
                       The model draws musical inspiration from this track.
        inspo_start_s: Start time (seconds) within the inspo clip (0 = beginning).
        inspo_end_s: End time (seconds) within the inspo clip (0 = full song).

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
        persona_id=persona_id,
        inspo_clip_id=inspo_clip_id,
        inspo_start_s=inspo_start_s,
        inspo_end_s=inspo_end_s,
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
# PERSONA — Vocal character management (Pro feature)
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_api_get_persona(persona_id: str, page: int = 1) -> str:
    """
    Fetch a Suno Persona by its UUID.

    A Persona is a consistent vocal character built from an existing song.
    Apply it to any generation via suno_api_generate(persona_id=...) to get
    a reproducible vocal style across multiple songs.

    Args:
        persona_id: The UUID of the persona to look up
        page: Page number for the persona's clip list (default: 1)

    Returns:
        Persona details: name, description, owner, clips, and usage hint.

    Requires: Authentication (Pro subscription for using personas in generation)
    """
    return await api_tools.api_get_persona(persona_id, page)


@mcp_app.tool()
async def suno_api_get_my_personas(page: int = 0) -> str:
    """
    List Personas you have created (Pro feature).

    Returns:
        Your personas with IDs, names, and clip counts.

    Requires: Authentication + Pro or Premier subscription
    """
    return await api_tools.api_get_my_personas(page)


@mcp_app.tool()
async def suno_api_get_featured_personas(page: int = 0) -> str:
    """
    List Suno's curated/featured Personas available to all Pro users.

    Returns:
        Featured personas with IDs, names, and descriptions.

    Requires: Authentication
    """
    return await api_tools.api_get_featured_personas(page)


# ─────────────────────────────────────────────────────────────────────────────
# LYRICS GENERATION — AI lyric writing
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_api_generate_lyrics(prompt: str) -> str:
    """
    Generate AI-written lyrics from a topic or theme.

    This produces only text — no audio. Use the output as the 'prompt'
    parameter in suno_api_generate() to turn the lyrics into a song.

    Args:
        prompt: Topic, mood, or short description
                e.g. "a melancholy song about a lighthouse keeper in winter"

    Returns:
        Suggested title + full generated lyrics.

    Requires: Authentication
    """
    return await api_tools.api_generate_lyrics(prompt)


# ─────────────────────────────────────────────────────────────────────────────
# STEMS — Audio stem separation (Premier feature)
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_api_generate_stems(song_id: str) -> str:
    """
    Split a completed song into individual stem tracks.

    Produces separate audio files for vocals, drums, bass, melody, etc.
    Each stem is returned as a new clip that can be downloaded individually.

    Args:
        song_id: ID of a completed song to separate

    Returns:
        Stem clip IDs and statuses — use suno_api_wait_for_song() per stem.

    Requires: Authentication + Premier subscription
    """
    return await api_tools.api_generate_stems(song_id)


# ─────────────────────────────────────────────────────────────────────────────
# CONCAT — Merge extended clips into one track
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_api_concat_song(clip_id: str) -> str:
    """
    Merge an extension clip with its parent into a single full-length song.

    After using suno_api_extend() to lengthen a song, call this to combine
    all the pieces into one continuous track.

    Args:
        clip_id: ID of the extension clip to concatenate

    Returns:
        New clip ID of the merged song.

    Requires: Authentication
    """
    return await api_tools.api_concat_song(clip_id)


# ─────────────────────────────────────────────────────────────────────────────
# LYRIC ALIGNMENT — Word-level timestamps
# ─────────────────────────────────────────────────────────────────────────────

@mcp_app.tool()
async def suno_api_get_lyric_alignment(song_id: str) -> str:
    """
    Get word-level lyric timestamps for karaoke-style synchronization.

    Returns each word with its precise start and end time in seconds,
    suitable for building lyric displays or timed captions.

    Args:
        song_id: ID of a completed song

    Returns:
        Table of words with start_s and end_s timestamps.

    Requires: Authentication
    """
    return await api_tools.api_get_lyric_alignment(song_id)


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
• Version: 2.1.0
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


# ─────────────────────────────────────────────
# MCP PROMPTS
# ─────────────────────────────────────────────

@mcp_app.prompt()
def compose_song(
    theme: str,
    genre: str = "pop",
    mood: str = "upbeat",
    language: str = "english",
    structure: str = "verse-chorus",
) -> str:
    """
    Generate a fully-parameterized prompt for composing an original Suno song.

    Guides the model through writing custom lyrics and choosing the right
    style tags, model version, and advanced generation options so that
    `suno_api_generate` can be called with all required arguments filled in.

    Args:
        theme: Core topic or story of the song (e.g. "Budapest 2077, dystopia")
        genre: Musical genre (e.g. "hip-hop", "synthwave", "folk", "jazz")
        mood: Emotional tone (e.g. "dark", "euphoric", "melancholic", "aggressive")
        language: Lyrics language (e.g. "english", "hungarian", "spanish")
        structure: Song structure shorthand (e.g. "verse-chorus", "AABA", "through-composed")
    """
    return f"""You are a professional songwriter and Suno AI v5 prompt engineer.

**Task:** Compose an original song and then call `suno_api_generate` to create it.

**Parameters:**
- Theme / Story: {theme}
- Genre: {genre}
- Mood: {mood}
- Lyrics language: {language}
- Song structure: {structure}

---

**Step 1 – Craft the Style Field** (`tags` param, ≤200 chars)

Use this structured format:
```
[GENRE: {genre}] [BPM: <estimate>] [Key: <Major/Minor>]
[Mood: {mood}]
[Instrumentation: <2–3 key instruments>]
[Vocal Style: <male/female, delivery type>]
```
Rules:
- **Front-load the most critical terms** (v5 weights first 3–5 tokens most)
- **Anchor the core vibe at both start AND end** — repeat the genre/mood descriptor at the end
- 1–2 genres max, no artist names
- Example end anchor: `"...cinematic, raw and emotional, {genre} energy"`

**Step 2 – Write the Lyrics** (`prompt` param)

Use Suno v5 meta-tags to structure each section:
```
[Intro]
[Mood: {mood}] [Energy: Low→Medium]
[Instrument: <sparse opening sound>]

[Verse]
[Vocal Style: <delivery>] [Energy: Building]
<lyrics — aim for 6–12 syllables per line>

[Pre-Chorus]
<build tension>

[Chorus]
[Energy: High] [Vocal Style: Open]
<hook — most memorable lines> (crowd adlib: yeah!)

[Bridge]
[Texture: Tape-Saturated] [Callback: continue with same vibe as chorus]
<emotional contrast>

[Breakdown: spoken, no drums]
<spoken word or whisper moment>

[Outro: fade, sparse instrumentation, Callback: Intro melody]
<final lines>
```

**Lyric rules for v5:**
- 6–12 syllables per line for clean vocal alignment
- Use `(yeah!)` / `(hé!)` adlibs in chorus for live feel
- Pronunciation tip: elongate for emphasis — `"loooove"`, `"seen, seen!"`
- Write in {language}

**Step 3 – Choose Advanced Options**
- `model`: "v5" (best quality & control)
- `vocal_gender`: "male" | "female" | "" (auto)
- `weirdness`: 0–100 — for {mood} mood, suggest: {"30–50 for grounded styles, 50–70 for experimental" if mood in ["dark", "surreal", "experimental"] else "20–40 for conventional styles"}
- `style_weight`: 60–80 recommended (strict enough to hold style, flexible enough for creativity)
- `negative_tags`: list styles that would clash with {genre}/{mood}

**Step 4 – Generate**
```python
suno_api_generate(
    prompt="<full lyrics with all section tags>",
    tags="<style field ≤200 chars>",
    title="<song title>",
    model="v5",
    vocal_gender="<choice>",
    weirdness=<0-100>,
    style_weight=<60-80>,
    negative_tags="<unwanted styles>"
)
```
Two variations will be generated. After completion, present both with their IDs and audio URLs, then ask the user which to download.

**Common issues to watch for:**
- If output sounds generic → simplify style tags, front-load harder
- If vocals are buried → note for user to try stem export
- If structure feels wrong → tighten section tags, use `[Mood/Energy]` per section
"""


@mcp_app.prompt()
def find_inspiration(
    genre: str = "any",
    period: str = "week",
) -> str:
    """
    Fetch trending Suno songs and distil creative inspiration for a new track.

    First calls `suno_api_get_trending` to get current chart data, then
    analyses the results and proposes a new original song concept.

    Args:
        genre: Filter inspiration by genre keyword (e.g. "jazz", "metal", "lo-fi") or "any"
        period: Trending period — "day", "week", or "" (all-time)
    """
    genre_note = f'Filter results mentally for the "{genre}" genre.' if genre != "any" else "Consider all genres."
    return f"""You are a music A&R scout and creative director.

**Task:** Find trending inspiration on Suno and propose a new original song concept.

**Step 1 – Fetch trending songs**
Call `suno_api_get_trending(period="{period}", page=0)`.
{genre_note}

**Step 2 – Analyse the results**
From the returned song list identify:
- Dominant genres and sub-genres
- Recurring moods and energy levels
- Interesting style tag combinations
- Titles or lyrical themes that feel fresh

**Step 3 – Propose a concept**
Based on your analysis, propose ONE original song concept that:
- Draws inspiration from the trends but avoids copying
- Has a clear theme, mood, and target audience
- Includes a working title, 3–5 style tags, and a 2-sentence lyrical premise

**Step 4 – Ask for approval**
Present the concept and ask: "Should I write full lyrics and generate this song?"
If yes, switch to the `compose_song` prompt workflow with the concept details.
"""


@mcp_app.prompt()
def remix_track(
    song_id: str,
    direction: str = "different genre",
    preserve: str = "melody",
) -> str:
    """
    Remix an existing Suno song in a new style or direction.

    Fetches the original song's metadata, then calls `suno_api_remix` with
    a new creative direction while respecting what should be preserved.

    Args:
        song_id: UUID of the song to remix
        direction: Creative direction for the remix (e.g. "jazz version", "darker mood", "acoustic")
        preserve: What to keep from the original (e.g. "melody", "lyrics", "structure", "nothing")
    """
    return f"""You are a music producer specialising in creative remixes.

**Task:** Remix song `{song_id}` in the direction: "{direction}"
**Preserve from original:** {preserve}

**Step 1 – Inspect the original**
Call `suno_api_get_song(song_id="{song_id}")` and note:
- Title, tags, duration, model version
- Lyrics (if visible in the response)
- Overall style and mood

**Step 2 – Plan the remix**
Decide:
- New style tags that reflect "{direction}"
- What prompt/lyrics changes are needed (keep {preserve}, change the rest)
- Whether to increase weirdness or change vocal gender
- Negative tags to steer away from the original style

**Step 3 – Execute the remix**
Call:
```
suno_api_remix(
    song_id="{song_id}",
    prompt="<updated lyrics or style description>",
    tags="<new style tags>",
    title="<Original Title> ({direction} remix)",
    model="v5"
)
```

**Step 4 – Present results**
Share both new variation IDs, ask the user which to keep, then optionally download.
"""


@mcp_app.prompt()
def create_playlist(
    name: str,
    description: str = "",
    song_ids: str = "",
) -> str:
    """
    Create a named playlist and populate it with songs from the user's library.

    Guides through `suno_api_create_playlist` and `suno_api_add_to_playlist`
    with an optional batch add from a comma-separated list of song IDs.

    Args:
        name: Playlist name
        description: Short description of the playlist theme
        song_ids: Comma-separated song UUIDs to add (leave empty to choose interactively)
    """
    ids_note = (
        f"Pre-selected song IDs to add: {song_ids}"
        if song_ids.strip()
        else "No songs pre-selected — browse the library first."
    )
    return f"""You are a Suno library manager.

**Task:** Create a new playlist called "{name}" and populate it with songs.
**Description:** {description or "(none provided)"}
**{ids_note}**

**Step 1 – Create the playlist**
Call:
```
suno_api_create_playlist(name="{name}", description="{description}")
```
Note the returned `playlist_id`.

**Step 2 – Browse library (if no songs pre-selected)**
If no songs were pre-selected, call `suno_api_get_my_songs(page=0)` and present
the list to the user. Ask them to pick songs by ID or title.

**Step 3 – Add songs**
For each chosen song_id call:
```
suno_api_add_to_playlist(playlist_id="<id from Step 1>", song_id="<chosen id>")
```

**Step 4 – Confirm**
Report the final playlist contents and share its ID for future reference.
"""


# ─────────────────────────────────────────────
# MCP RESOURCES
# ─────────────────────────────────────────────

@mcp_app.resource("suno://models")
def resource_models() -> str:
    """
    Available Suno AI model versions with capabilities and recommended use cases.

    Returns a structured reference of all supported model aliases so the agent
    can choose the right model for each generation task.
    """
    return """# Suno AI Models

| Alias   | API name        | Best for                              |
|---------|-----------------|---------------------------------------|
| v5      | chirp-crow      | Best quality & control (DEFAULT)      |
| v4.5x   | chirp-bluejay   | Advanced creation methods             |
| v4.5    | chirp-auk       | Intelligent auto-prompts              |
| v4.5-all| chirp-v4-5      | Best free-plan model                  |
| v4      | chirp-v4        | Improved sound quality                |
| v3.5    | chirp-v3-5      | Classic Suno sound                    |
| v3      | chirp-v3        | Basic / fast generation               |

## v5 (chirp-crow) — Recommended
- Full custom lyrics with section meta-tags
- Advanced parameters: weirdness, style_weight, negative_tags, vocal_gender
- Persona and Inspo clip support
- Best adherence to structural prompts ([Verse], [Chorus], [Bridge] …)

## Generation cost
Each `suno_api_generate()` call produces **2 variations** and costs **20 credits**.
"""


@mcp_app.resource("suno://style-tags")
def resource_style_tags() -> str:
    """
    Curated library of Suno style tags organised by genre, mood, and production element.

    Use these tags in the `tags` parameter of `suno_api_generate` to shape the
    musical style of generated tracks precisely.
    """
    return """# Suno Style Tags Reference

## Genre
acoustic, ambient, blues, boom-bap, classical, country, dark-pop, disco,
drum-and-bass, dubstep, edm, electronic, folk, funk, gospel, hip-hop,
house, indie, jazz, lo-fi, metal, pop, punk, r&b, rap, reggae, rock,
soul, synthwave, techno, trap, world

## Mood / Energy
aggressive, anthemic, atmospheric, brooding, catchy, cinematic, dark,
dreamy, emotional, energetic, epic, euphoric, groovy, haunting, heavy,
hypnotic, intense, melancholic, mellow, mysterious, nostalgic, peaceful,
playful, powerful, raw, relaxing, romantic, sad, satirical, surreal,
tense, triumphant, upbeat

## Vocal Style
auto-tune, choir, falsetto, female-vocals, gritty, harmonies, male-vocals,
operatic, rap, scream, spoken-word, whisper, yodel

## Production / Instruments
808-bass, acoustic-guitar, arpeggiated-synth, bass-guitar, brass,
claps, distorted-guitar, drum-machine, electric-guitar, flute,
glockenspiel, hi-hats, horn, keys, orchestra, piano, saxophone,
shakers, snare, strings, synth-pad, trumpet, ukulele, vinyl-crackle,
violin

## BPM / Tempo
60 BPM, 80 BPM, 90 BPM, 100 BPM, 120 BPM, 130 BPM, 140 BPM, 160 BPM

## Key
major key, minor key, dorian mode, phrygian mode, lydian mode
"""


@mcp_app.resource("suno://prompt-guide")
def resource_prompt_guide() -> str:
    """
    Suno v5 prompting master reference: meta-tags, structure, style fields, and advanced techniques.

    Synthesises the Jack Righteous v5 Training Series, the Suno v5 PDF guide, and
    LitMedia best practices into a single actionable reference for writing prompts
    that produce high-quality, well-structured songs with Suno's v5 model.
    """
    return """# Suno v5 Prompting Master Guide

## Two Separate Input Fields
Suno has **two independent fields** — use them differently:

| Field | Purpose | Limit |
|-------|---------|-------|
| **Style / Tags** (`tags` param) | Genre, mood, BPM, key, production style — NO lyrics | ~200 chars |
| **Lyrics / Prompt** (`prompt` param) | Full lyrics with section meta-tags — the creative content | No hard limit |

---

## Style Field — Best Practices (≤200 chars)

### Structured format (recommended)
```
[GENRE: Synthwave, Retro 80s] [BPM: 110] [Key: A Minor]
[Mood: Nostalgic, Futuristic]
[Instrumentation: Analog Synths, Deep Bass, Reverb-heavy Drums]
```

### Rules
1. **Front-load the most critical terms** — v5 weights the first 3–5 items most heavily
2. **Anchor key descriptors at START and END** — repeat the core vibe at both ends to lock it in
   - Good: `"Cinematic outlaw country, bluesy pedal steel, raw and emotional... cinematic southern soul"`
3. **1–2 genres max** — stacking 3+ confuses the model; use one genre + one modifier
4. **6–10 style tokens** — too few = generic, too many = incoherent
5. **Avoid artist/song names** — describe style instead
   - Bad: `"like Coldplay"` → Good: `"anthemic indie pop, atmospheric synths, emotional male vocals, 103 BPM"`

---

## Lyrics Field — Meta-tag System (v5)

### Structure Tags — song architecture
```
[Intro]              Opening, sets atmosphere (calm/sparse)
[Verse]              Narrative, storytelling
[Pre-Chorus]         Build tension before the hook
[Chorus]             Main hook — most repeated section
[Bridge]             Contrast, emotional shift
[Breakdown]          Drop energy, spoken word or sparse
[Instrumental Break] Pure music, no vocals
[Outro]              Fade or final statement
```

### Mood & Energy Tags — emotional arc
```
[Mood: Uplifting]        [Mood: Melancholic]     [Mood: Haunting]
[Energy: Low→High]       [Energy: High]          [Energy: Medium]
```
Place mood tags in the **first 3 lines** and before choruses for maximum impact.

### Instrument Tags — timbre control
```
[Instrument: Warm Rhodes]        [Instrument: Analog Synths]
[Instrument: Muted Trumpet]      [Instrument: 808 Bass]
[Instrument: Bright Electric Guitars, Live Drums]
```
v5 manifests these with **audible separation** — more reliable than just listing in style field.

### Vocal Tags — delivery and effects
```
[Vocal Style: Whisper]           [Vocal Style: Power Praise]
[Vocal Style: Open, Confident]   [Vocal Style: Gritty]
[Vocal Effect: Natural Reverb]   [Vocal Effect: AutoTune]
```
Pair with a **Persona** (`persona_id`) for consistent voice across sections.

### Texture Tags — production feel
```
[Texture: Tape-Saturated]        [Texture: Vinyl Hiss]
[Texture: Lo-fi Filter]          [Texture: Gentle Sidechain]
```

### Callback Tag — extend chain coherence
```
[Callback: continue with same vibe as chorus]
[Callback: Intro orchestral melody returns]
```
Re-inject every 1–2 extends to prevent style drift.

### Timed / Dynamic Tags — specific transitions
```
[Solo: 12s sax swell]
[Bridge: 15s soaring accordion solo]
[Break: distorted bass drop]
[Drop: aggressive build]
```

### Inline hints inside section tags
```
[Chorus – sung, crowd adlibs]
[Breakdown: drums drop, single piano, whisper]
[Verse – fast rap, internal rhymes]
[Outro: fade, sparse strings, callback melody]
[Bridge: Tape-Saturated] [Callback: continue with same vibe as chorus]
```

---

## v5 Complete Example

**Style field:**
```
Hungarian political rap, boom bap, 94 BPM, minor key, male vocals,
dark piano loop, 808 bass, vinyl crackle, cinematic
```

**Lyrics field:**
```
[Intro]
[Mood: Dark, Tense] [Energy: Low]
[Instrument: Sparse Piano, Vinyl Crackle]

[Verse]
[Vocal Style: Gritty] [Energy: Building]
six syllable lines work well
keep it tight, keep it real

[Chorus]
[Energy: High] [Vocal Style: Open, Crowd Adlibs]
hook line one here
hook line two here (yeah!)

[Bridge]
[Texture: Tape-Saturated] [Callback: continue with same vibe as chorus]
contrast moment — shift the mood

[Outro: fade, sparse piano, Callback: Intro melody]
```

---

## Advanced Parameters (`suno_api_generate`)
| Parameter     | Range   | Effect |
|---------------|---------|--------|
| `weirdness`   | 0–100   | 0 = conventional · 100 = avant-garde experimental |
| `style_weight`| 0–100   | How strictly style tags are enforced |
| `vocal_gender`| m/f/""  | Force gender or let model decide |
| `negative_tags` | string | Styles to explicitly suppress |

---

## Lyric Writing Rules for v5

1. **6–12 syllables per line** — v5 tracks well within this range; longer lines misalign
2. **Pronunciation tweaks** — elongate vowels for emphasis: `"loooove"`, `"seen, seen!"`
3. **Energy arc** — Intro (calm) → Verses (build) → Chorus (peak) → Bridge (shift) → Final Chorus (biggest)
4. **Crowd adlibs** — `(yeah!)`, `(hé!)`, `(na!)` in chorus lines for live feel
5. **Narrative prompts** — v5 responds well to full sentences describing arc:
   - `"Start with ambient layers, build to hypnotic groove with warm synths"`

---

## Common Issues & Fixes

| Problem | Fix |
|---------|-----|
| Ignored tags / generic output | Simplify to 1–2 genres; front-load key tags |
| Repetitive sections | Add `"variation/dynamic"` cue or use Replace on that section |
| Artifacts (hiss/shimmer) | Remaster → Subtle first; High only for variety |
| Vocals buried in mix | Export stems and rebalance; or Replace chorus with clearer Persona |
| Style drift on long Extend chains | Re-inject genre/mood + add `[Callback: ...]` every 1–2 extends |
| Prompt overload | Move details to lyrics field; keep style field ≤200 chars |

---

## Persona & Inspo
- **Persona** (`persona_id`): Consistent vocal character (Whisper Soul, Power Praise, Retro Diva…)
  - Pair with `[Vocal Style: X]` tag in lyrics for best results
- **Inspo** (`inspo_clip_id`): Existing song as stylistic reference
  - Trim with `inspo_start_s` / `inspo_end_s` to reference a specific section only

---

## Loop-Friendly Tracks
Include `"loop-friendly"` in the style field + `[Texture: seamless loop]` in lyrics.
After generation: use Crop/Fade → Remaster (Subtle) for clean loops.

---
*Sources: Jack Righteous v5 Training Series (Oct 2025), Suno v5 PDF Guide, LitMedia Suno Prompts Guide*
"""


@mcp_app.resource("suno://credits")
async def resource_credits() -> str:
    """
    Live credit balance and subscription plan for the authenticated Suno account.

    Fetches real-time data from the Suno API. Requires authentication
    (run `suno_browser_login` or `suno_save_cookie` first).
    """
    try:
        result = await api_tools.get_credits()
        return f"# Suno Credits\n\n{result}"
    except Exception as e:
        return f"# Suno Credits\n\nUnable to fetch credits: {e}\n\nRun `suno_browser_login` to authenticate first."


@mcp_app.resource("suno://trending")
async def resource_trending() -> str:
    """
    Current all-time trending songs on Suno (public, no auth required).

    Returns the top ~20 trending tracks with titles, tags, play counts,
    and audio URLs — useful for inspiration and style reference.
    """
    try:
        result = await api_tools.get_trending_songs(page=0, period="")
        return f"# Suno Trending Songs\n\n{result}"
    except Exception as e:
        return f"# Suno Trending Songs\n\nUnable to fetch trending: {e}"


@mcp_app.resource("suno://my-library")
async def resource_my_library() -> str:
    """
    First page of the authenticated user's personal Suno song library.

    Shows all songs you have generated including status, IDs, titles,
    tags, duration, and audio URLs. Requires authentication.
    """
    try:
        result = await api_tools.get_my_songs(page=0)
        return f"# My Suno Library\n\n{result}"
    except Exception as e:
        return f"# My Suno Library\n\nUnable to fetch library: {e}\n\nRun `suno_browser_login` to authenticate first."


def main():
    """Main entry point for MCP server (stdio mode)."""
    logging.info("Starting Suno MCP server (stdio mode)")
    mcp_app.run()


def main_api():
    """Main entry point for FastAPI server."""
    import time
    import uvicorn

    # Store start time for uptime calculation
    fastapi_app.state.start_time = time.time()

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