# Suno-MCP

**Model Context Protocol server for Suno AI music generation.**  
Full API integration with v5 model support, secure session management, advanced generation parameters, and library management — all controllable from Claude Desktop or any MCP client.

> Forked from [sandraschi/suno-mcp](https://github.com/sandraschi/suno-mcp) and significantly extended by [@arlinamid](https://github.com/arlinamid).

---

## What This Does

- **Login once** — credentials and session cookies are stored securely (OS keyring + DPAPI/Fernet encryption)
- **Generate music** — v5 (chirp-crow), v4.5x, v4.5, v4, v3.5 model support with full advanced options
- **Advanced mode** — separate lyrics & style prompts, vocal gender, weirdness, style influence, negative tags
- **Manage your library** — browse songs, playlists, liked songs; create/edit playlists
- **Download** — save MP3/artwork files from your library or directly by song ID
- **Auto session refresh** — Clerk JWT tokens are refreshed automatically before they expire

---

## How Generation Works

Suno's generation endpoint is protected by **hCaptcha**. This MCP uses a **browser-assisted strategy**:

1. Opens a Chromium window (~15 seconds, non-headless)
2. Navigates to `suno.com/create`, switches to Advanced mode, fills the form fields
3. Clicks "Create" — the browser solves hCaptcha naturally
4. **Intercepts** the outgoing `POST /generate/v2-web/` request and **replaces the body** with your exact parameters (preserving the hCaptcha token)
5. Captures the API response and closes the browser

This means generation always produces **2 variations** per call (Suno's default), the window appears briefly and then closes automatically, and all advanced parameters are reliably injected.

---

## Installation

### Prerequisites
- Python 3.10+
- Claude Desktop (or any MCP client)
- A [Suno AI](https://suno.com) account (free tier works)

### Setup

```bash
# 1. Clone
git clone https://github.com/arlinamid/suno-mcp.git
cd suno-mcp

# 2. Install Python dependencies
pip install -e .

# 3. Install Playwright browser
playwright install chromium
```

### Configure Claude Desktop

Add to `claude_desktop_config.json`:

**Windows** (`%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "suno-mcp": {
      "command": "python",
      "args": ["-m", "suno_mcp.server"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\suno-mcp\\src"
      }
    }
  }
}
```

**macOS / Linux** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "suno-mcp": {
      "command": "python",
      "args": ["-m", "suno_mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/suno-mcp/src"
      }
    }
  }
}
```

Restart Claude Desktop after saving.

---

## First-Time Login

Run this once to authenticate and save your session securely:

```bash
python -c "import asyncio; from suno_mcp.tools.api.tools import ApiSunoTools; asyncio.run(ApiSunoTools().browser_login())"
```

A browser window will open — log in to Suno normally. The session (including HTTP-only cookies) is saved encrypted to your OS keyring. Future calls will use the saved session and auto-refresh it as needed.

---

## Example Usage (Claude Desktop)

```
"Generate a dark synthwave track with female vocals about neon rain"

"Create a song titled 'Mountain Dawn' — acoustic folk, male voice, weirdness 30"

"Show me my Suno library"

"Download song <id> to D:\Music"

"Create a playlist called 'Chill Vibes' and add song <id>"
```

---

## Tools Reference

### Session & Authentication

| Tool | Description |
|------|-------------|
| `suno_browser_login` | Open browser, log in to Suno, save session |
| `suno_refresh_session` | Force-refresh the Clerk JWT token |
| `suno_session_info` | Show current session status and expiry |
| `suno_credential_status` | List what credentials are stored |
| `suno_save_cookie` | Manually save a cookie value |
| `suno_save_token` | Manually save an auth token |
| `suno_clear_credentials` | Delete all stored credentials |
| `suno_api_check_auth` | Verify the current session is valid |

### Generation

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `suno_api_generate` | Generate a new song (2 variations) | `prompt`, `tags`, `title`, `model`, `vocal_gender`, `weirdness`, `style_weight`, `negative_tags`, `make_instrumental` |
| `suno_api_extend` | Extend an existing song | `song_id`, `prompt`, `continue_at` |
| `suno_api_remix` | Remix a song with new style | `song_id`, `tags`, `prompt` |
| `suno_api_inpaint` | Replace a section of a song | `song_id`, `prompt`, `start_s`, `end_s` |
| `suno_api_wait_for_song` | Poll until a song's audio is ready | `song_id`, `timeout` |

**Model aliases for `model` parameter:**

| Alias | Suno Model |
|-------|-----------|
| `v5` / `chirp-crow` | Suno v5 (latest) |
| `v4.5x` / `chirp-v4-5-extended` | v4.5 Extended |
| `v4.5` / `chirp-v4-5` | v4.5 |
| `v4` / `chirp-v4` | v4 |
| `v3.5` / `chirp-v3-5` | v3.5 |
| `v3` / `chirp-v3` | v3 |

### Library & Discovery

| Tool | Description |
|------|-------------|
| `suno_api_get_my_songs` | Your generated songs (paginated) |
| `suno_api_get_liked_songs` | Songs you have liked |
| `suno_api_get_my_playlists` | Your playlists |
| `suno_api_get_playlist` | Songs in a specific playlist |
| `suno_api_get_song` | Details for a single song by ID |
| `suno_api_search` | Search public songs |
| `suno_api_get_trending` | Trending songs feed |
| `suno_api_get_contests` | Current contests/challenges |

### Playlist Management

| Tool | Description |
|------|-------------|
| `suno_api_create_playlist` | Create a new playlist |
| `suno_api_add_to_playlist` | Add a song to a playlist |
| `suno_api_remove_from_playlist` | Remove a song from a playlist |
| `suno_api_update_playlist` | Rename or update playlist description |

### Song Actions

| Tool | Description |
|------|-------------|
| `suno_api_like_song` | Like a song |
| `suno_api_delete_song` | Delete one of your songs |
| `suno_api_make_public` | Make a song public |

### Download

| Tool | Description |
|------|-------------|
| `suno_api_download_song` | Download a song (MP3 + optional artwork) |
| `suno_api_download_playlist` | Download all songs in a playlist |
| `suno_api_download_my_songs` | Download your entire library (paginated) |

### Account

| Tool | Description |
|------|-------------|
| `suno_api_get_credits` | Check remaining credits |
| `suno_api_get_subscription_plans` | List available subscription plans |

### Legacy Browser Tools

These older tools are still available for compatibility but the API tools above are preferred:

| Tool | Description |
|------|-------------|
| `suno_open_browser` | Launch a Playwright browser |
| `suno_login` | Log in via browser automation |
| `suno_generate_track` | Generate via browser UI |
| `suno_download_track` | Download via browser |
| `suno_get_status` | Browser session status |
| `suno_close_browser` | Close browser session |

---

## Advanced Generation Parameters

When calling `suno_api_generate`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | required | Lyrics or generation prompt |
| `tags` | string | `""` | Style tags (e.g. `"dark synthwave, female vocals"`) |
| `title` | string | `""` | Song title |
| `model` | string | `"chirp-crow"` | Model version (see aliases above) |
| `make_instrumental` | bool | `false` | Generate without vocals |
| `vocal_gender` | string | `null` | `"male"` or `"female"` |
| `weirdness` | int | `50` | 0–100, higher = more experimental |
| `style_weight` | int | `50` | 0–100, influence of style tags vs prompt |
| `negative_tags` | string | `""` | Styles to avoid (e.g. `"heavy metal, distortion"`) |

---

## Project Structure

```
suno-mcp/
├── src/suno_mcp/
│   ├── server.py                    # MCP tool registration (FastMCP)
│   └── tools/
│       ├── api/
│       │   └── tools.py             # All API + browser-assisted tools
│       └── shared/
│           ├── api_client.py        # httpx async API client
│           ├── credentials.py       # Secure keyring + DPAPI/Fernet storage
│           └── session_manager.py   # Clerk JWT decode, expiry, refresh
├── scripts/
│   ├── intercept_generate.py        # Dev tool: intercept generate requests
│   ├── find_models.py               # Dev tool: scrape model IDs from JS bundles
│   └── find_create_button.py        # Dev tool: inspect Create button DOM state
├── tests/
│   ├── unit/                        # Unit tests (no network required)
│   └── local/                       # Live integration tests (requires login)
├── pyproject.toml
├── requirements.txt
├── pyrightconfig.json
└── README.md
```

---

## Security

Credentials are stored using your OS's native secure storage:

- **Session cookies / tokens** — stored in the OS keyring (Windows Credential Manager, macOS Keychain, libsecret on Linux)
- **Large values** (cookie jar > 1800 bytes) — encrypted with **Windows DPAPI** (Windows) or **Fernet AES** (macOS/Linux), key stored in keyring, encrypted file saved to `%APPDATA%\suno-mcp\` (Windows) or `~/.config/suno-mcp/`
- **No plaintext secrets** in logs, config files, or environment variables
- **JWT tokens are auto-refreshed** using Clerk's silent refresh API before expiry

---

## Running Tests

```bash
# Unit tests (no Suno account needed)
pytest tests/unit/ -v

# Live integration tests (requires prior login)
pytest tests/local/ -v -s
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `suno_api_check_auth` returns unauthenticated | Run `suno_browser_login` to re-authenticate |
| Browser window doesn't close | Generation timed out; check logs for errors |
| `422 Token validation failed` | Session expired; run `suno_refresh_session` |
| Create button stays disabled | Suno UI changed; check `scripts/find_create_button.py` |
| Credits show 0 | Free tier limit reached or subscription expired |
| DPAPI decrypt warning on startup | Harmless on first run; credentials will be re-saved correctly |

---

## License

MIT License — see [LICENSE](LICENSE)

---

**Fork of**: [sandraschi/suno-mcp](https://github.com/sandraschi/suno-mcp)  
**Extended by**: [@arlinamid](https://github.com/arlinamid)  
**Last updated**: 2026-03-12
