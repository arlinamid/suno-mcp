# Changelog

All notable changes to this project are documented here.

---

## [Unreleased] — arlinamid fork

> Base: [sandraschi/suno-mcp](https://github.com/sandraschi/suno-mcp) @ `0402a9f`

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

[Unreleased]: https://github.com/arlinamid/suno-mcp/compare/v1.0.0...HEAD  
[2.0.0]: https://github.com/arlinamid/suno-mcp/releases/tag/v2.0.0  
[1.0.0]: https://github.com/sandraschi/suno-mcp/releases/tag/v1.0.0
