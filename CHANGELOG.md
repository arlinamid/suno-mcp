# Changelog

All notable changes to this project are documented here.

---

## [Unreleased] — arlinamid fork

> Base: [sandraschi/suno-mcp](https://github.com/sandraschi/suno-mcp) @ `0402a9f`

---

## [2.2.0] — 2026-03-13

Feature release adding a full-featured terminal CLI (`suno` command).

### Added

#### CLI (`src/suno_mcp/cli.py`)
A new `suno` command installed as a script entry-point (`pip install -e .`):

| Command group | Commands |
|---|---|
| **Auth** | `login`, `status`, `refresh`, `clear-auth` |
| **Generate** | `generate`, `wait`, `extend`, `remix`, `lyrics` |
| **Library** | `songs`, `song`, `trending`, `search`, `liked` |
| **Playlists** | `playlists`, `playlist`, `playlist-create`, `playlist-add`, `playlist-remove` |
| **Download** | `download`, `download-playlist`, `download-library` |
| **Song actions** | `like`, `publish`, `delete` |
| **Account** | `credits`, `contests`, `plans` |
| **Advanced** | `stems`, `concat` |
| **Help** | `info` (full reference table) |

Key features:
- Built on [Typer](https://typer.tiangolo.com/) with [Rich](https://rich.readthedocs.io/) output
- `--wait` and `--download DIR` flags on `generate` for one-shot generation + download
- `--json` flag on `songs` and `song` for machine-readable output
- Spinner progress indicators for long operations
- Windows UTF-8 console fix (forces `SetConsoleOutputCP(65001)` on startup)
- `suno info` prints a full ASCII command-reference table

#### Dependencies
- `typer>=0.12.0` and `rich>=13.0.0` added to `[project.dependencies]` in `pyproject.toml`
- `suno` entry-point added to `[project.scripts]`

#### Documentation
- README: new **CLI Usage** section with full example commands
- CONTRIBUTING.md: new **CLI Development** section (running without install, adding commands, style guidelines)

---

## [2.1.0] — 2026-03-13

Feature release adding MCP Prompts and Resources, a major prompt-guide upgrade, and two type-error bug fixes.

### Added

#### MCP Prompts (`@mcp_app.prompt()`)
Four reusable prompt templates that guide an LLM through complete Suno workflows:
- **`compose_song`** — Full song composition workflow: writes style field (≤200 chars, anchor technique), structures lyrics with v5 meta-tags (`[Mood]`, `[Energy]`, `[Instrument]`, `[Texture]`, `[Callback]`), picks advanced parameters, and calls `suno_api_generate`. Params: `theme`, `genre`, `mood`, `language`, `structure`
- **`find_inspiration`** — Fetches trending songs, analyses dominant genres/moods, and proposes an original song concept. Params: `genre`, `period`
- **`remix_track`** — Inspects an existing song's metadata then calls `suno_api_remix` with a new creative direction. Params: `song_id`, `direction`, `preserve`
- **`create_playlist`** — Creates a named playlist and populates it from the library. Params: `name`, `description`, `song_ids`

#### MCP Resources (`@mcp_app.resource()`)
Six contextual data sources accessible to any MCP client:

| URI | Type | Content |
|-----|------|---------|
| `suno://models` | static | All model aliases with API names and use cases |
| `suno://style-tags` | static | Curated tag catalogue: genre, mood, vocal, production, BPM, key |
| `suno://prompt-guide` | static | v5 prompting master reference (see below) |
| `suno://credits` | live API | Current credit balance and subscription plan |
| `suno://trending` | live API | Top trending songs feed |
| `suno://my-library` | live API | User's personal song library (page 0) |

#### `suno://prompt-guide` — major content upgrade
Completely rewritten, synthesising the *Jack Righteous v5 Training Series* (Oct 2025), the *Suno v5 PDF Guide*, and *LitMedia Suno Prompts Guide*:
- **Two-field model** — style field (≤200 chars) vs lyrics field, both explained with rules
- **Anchor descriptor technique** — repeat the core vibe at the start AND end of the style field
- **Full tag taxonomy**: `[Mood: X]`, `[Energy: X]`, `[Instrument: X]`, `[Texture: X]`, `[Vocal Style: X]`, `[Vocal Effect: X]`, `[Callback: ...]`, timed tags (`[Solo: 12s sax swell]`)
- **Lyric writing rules**: 6–12 syllables/line, pronunciation tweaks, crowd adlibs
- **Common issues & fixes table**: ignored tags, repetition, artifacts, buried vocals, extend drift
- **Loop-friendly track guide**

### Fixed
- `asyncio.run(mcp_app.run())` → `mcp_app.run()` — FastMCP `.run()` is synchronous; wrapping in `asyncio.run()` passed `None` to the coroutine parameter
- `fastapi_app.start_time` → `fastapi_app.state.start_time` — FastAPI does not allow arbitrary attribute assignment on the app object; `state` is the correct slot

### Changed
- Version bumped `1.0.0` → `2.1.0` in `pyproject.toml`, `server.py` (HealthResponse, FastAPI init, health endpoint, status tool)
- `compose_song` prompt updated with v5-specific guidance: front-loading, anchor repeat, syllable count, per-section energy/instrument tags, common issue hints

---

## [2.0.0] — 2026-03-12

Complete rewrite of the generation engine and a major feature expansion on top of the original browser-automation-only implementation.

### Added

#### Generation
- **Browser-assisted generation with hCaptcha bypass** (`suno_api_generate`)  
  Opens a non-headless Chromium window, fills the Advanced mode form, clicks "Create" so the browser solves hCaptcha naturally, then intercepts the outgoing `POST /generate/v2-web/` request and replaces the body with exact parameters — preserving the hCaptcha token. Browser closes automatically after ~15 s.
- **v5 model support** — `chirp-crow` and aliases `v5`, `v4.5x`, `v4.5`, `v4`, `v3.5`, `v3`
- **Advanced generation parameters**: `vocal_gender` (male/female), `weirdness` (0–100), `style_weight` (0–100), `negative_tags`
- **Exact DOM selectors** for all Advanced mode fields (lyrics textarea, style textarea, gender buttons, weirdness slider, style influence slider, title input) with primary + fallback selector logic
- **Extend, remix, inpaint** tools (`suno_api_extend`, `suno_api_remix`, `suno_api_inpaint`)
- `suno_api_wait_for_song` — polls until audio URL is ready

#### API Client (`tools/shared/api_client.py`)
- Full async `httpx` client for `studio-api.prod.suno.com`
- Endpoints: credits, billing, subscription plans, feed, search, playlists, liked songs, contests
- Automatic `Authorization: Bearer <token>` and `browser-token` header injection
- Streaming file downloads with progress (MP3 + artwork)

#### Session Management (`tools/shared/session_manager.py`)
- JWT decode and expiry checking (no external library needed)
- Silent Clerk JWT refresh via `https://clerk.suno.com/v1/client/sessions/{sid}/tokens`
- Auto-refresh triggered before token expiry on every API call
- `suno_refresh_session`, `suno_session_info` MCP tools

#### Secure Credential Storage (`tools/shared/credentials.py`)
- OS keyring integration via `keyring` library (Windows Credential Manager / macOS Keychain / libsecret)
- **Large-value encryption** for values > 1800 bytes (full cookie jar exceeds Windows Credential Manager limit):
  - **Windows**: DPAPI (`win32crypt.CryptProtectData`) — encrypted file in `%APPDATA%\suno-mcp\`
  - **macOS / Linux**: Fernet AES-128-CBC (`cryptography` library) — key in keyring, file in `~/.config/suno-mcp/`
- `suno_credential_status`, `suno_save_cookie`, `suno_save_token`, `suno_clear_credentials` MCP tools

#### Library & Discovery
- `suno_api_get_my_songs` — paginated personal library
- `suno_api_get_liked_songs` — liked songs feed
- `suno_api_get_my_playlists` — personal playlists
- `suno_api_get_playlist` — songs in a playlist
- `suno_api_get_song` — single song details
- `suno_api_search` — public song search
- `suno_api_get_trending` — trending feed with period filter
- `suno_api_get_contests` — active contests

#### Playlist Management
- `suno_api_create_playlist`
- `suno_api_add_to_playlist`
- `suno_api_remove_from_playlist`
- `suno_api_update_playlist`

#### Downloads
- `suno_api_download_song` — MP3 + optional artwork by song ID
- `suno_api_download_playlist` — full playlist download
- `suno_api_download_my_songs` — bulk download personal library

#### Song Actions
- `suno_api_like_song`, `suno_api_delete_song`, `suno_api_make_public`

#### Tests
- Full unit test suite (`tests/unit/`) — no network required, all external calls mocked
  - `test_api_client.py`, `test_api_tools.py`, `test_credentials.py`, `test_server_tools.py`, `test_session_manager.py`
- Live integration tests (`tests/local/test_live_api.py`) — runs against real Suno API
- `pytest-asyncio` configured with `asyncio_default_test_loop_scope = "module"` to prevent event loop issues

#### Developer Scripts
- `scripts/intercept_generate.py` — Playwright script to capture full `generate/v2-web` request/response for reverse engineering
- `scripts/find_models.py` — scrapes Suno's JS bundles for model identifiers
- `scripts/find_create_button.py` — dumps Create button DOM state and takes screenshot

#### Tooling
- `pyrightconfig.json` — basedpyright strict type checking configuration
- Updated `pyproject.toml` with test config and new dependencies

### Changed
- `server.py` — registered all 37 new MCP tools; updated `suno_api_generate` docstring to accurately describe browser-assisted mechanism (not direct API)
- `requirements.txt` — added `httpx`, `keyring`, `cryptography`, `pywin32`, `pytest`, `pytest-asyncio`, `basedpyright`
- `pyproject.toml` — version bumped, keywords updated, test configuration added

### Fixed
- `OSError: [WinError 1783] The stub received bad data` — Windows Credential Manager byte limit exceeded by cookie jar; fixed with DPAPI file-based encryption
- `DPAPI decrypt failed` warning on startup — fixed by detecting Fernet-encrypted data (`gA` prefix) before attempting DPAPI decryption
- `422 Token validation failed` — resolved by using browser-assisted route-intercept strategy instead of direct API calls (hCaptcha requirement)
- `AttributeError: 'list' object has no attribute 'get'` in `get_my_songs` — API returns list or dict depending on context; both handled
- `API error 404` for liked songs — correct endpoint is `/feed/?filter=liked`, not `/feed/liked/`
- `RuntimeError: Event loop is closed` in async tests — fixed with module-scoped pytest-asyncio event loop
- `SyntaxError: Failed to execute querySelector` — replaced JS `:has-text()` (Playwright-only) with native `page.locator()`

---

## [1.0.0] — 2025-01-27 (sandraschi/suno-mcp)

Original implementation by [@sandraschi](https://github.com/sandraschi).

### Included
- Basic MCP server with FastMCP 2.12
- Playwright browser automation for Suno login, generation, download
- Dual interface: stdio (Claude Desktop) + FastAPI HTTP
- Tools: `suno_open_browser`, `suno_login`, `suno_generate_track`, `suno_download_track`, `suno_get_status`, `suno_close_browser`
- Cursor rulebook and documentation

---

[Unreleased]: https://github.com/arlinamid/suno-mcp/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/arlinamid/suno-mcp/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/arlinamid/suno-mcp/releases/tag/v2.0.0
[1.0.0]: https://github.com/sandraschi/suno-mcp/releases/tag/v1.0.0
