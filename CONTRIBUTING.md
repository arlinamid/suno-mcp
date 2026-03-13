# Contributing to suno-mcp

Thanks for your interest in contributing.  
This is a **Python** project (v2.1.0) — please ignore any older Node.js references.

---

## Quick Start

```bash
# 1. Fork + clone
git clone https://github.com/arlinamid/suno-mcp.git
cd suno-mcp

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. Install in editable mode with dev extras
pip install -e ".[dev]"

# 4. Install Playwright browsers
playwright install chromium

# 5. Verify
pytest tests/unit/ -v
```

---

## Project Structure

```
suno-mcp/
├── src/suno_mcp/
│   ├── server.py                    # All MCP tool / prompt / resource registration
│   ├── cli.py                       # `suno` CLI entry-point (Typer + Rich)
│   └── tools/
│       ├── api/
│       │   └── tools.py             # ApiSunoTools — all API + browser-assisted tools
│       ├── basic/
│       │   └── tools.py             # BasicSunoTools — legacy browser tools
│       └── shared/
│           ├── api_client.py        # httpx async client for studio-api.prod.suno.com
│           ├── credentials.py       # OS keyring + DPAPI/Fernet secure storage
│           └── session_manager.py   # Clerk JWT decode, expiry, auto-refresh
├── tests/
│   ├── unit/                        # Fully mocked — no network required
│   └── local/                       # Live integration tests (requires login)
├── scripts/                         # Dev utilities (intercept, model scraper, …)
├── pyproject.toml
├── pyrightconfig.json
└── requirements.txt
```

---

## CLI Development

The `suno` CLI lives in `src/suno_mcp/cli.py` and is built with [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/).

### Running without installing

```bash
# PowerShell
$env:PYTHONPATH="src"; python -m suno_mcp.cli --help
$env:PYTHONPATH="src"; python -m suno_mcp.cli status
```

### Adding a new CLI command

Each command is a regular Typer function decorated with `@app.command()`. It calls `_run(coro)` to execute async `ApiSunoTools` methods synchronously:

```python
@app.command()
def my_command(
    song_id: Annotated[str, typer.Argument(help="Song UUID")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """One-line description shown in --help."""
    result = _run(_t().some_api_method(song_id=song_id))
    console.print(result)
```

Guidelines:
- Keep all strings ASCII-safe (Windows cp1250 default codepage; UTF-8 is forced at startup via `SetConsoleOutputCP(65001)` but write defensively)
- Use `_ok(msg)` for simple success confirmations, `_err(msg)` for fatal errors
- Wrap long operations in a `Progress(SpinnerColumn(), ...)` context for visual feedback
- Add the command to the `info` table rows list for the quick-reference view
- Update `CHANGELOG.md` under `[Unreleased]`

---

## Adding a New MCP Tool

All tools are registered in `server.py` with the `@mcp_app.tool()` decorator.

```python
@mcp_app.tool()
async def suno_my_tool(param_one: str, param_two: int = 0) -> str:
    """
    One-line summary shown in the MCP inspector.

    Longer description explaining what the tool does, when to use it,
    and any requirements (e.g. authentication).

    Args:
        param_one: Description of param_one
        param_two: Description of param_two (default: 0)

    Returns:
        Human-readable result string
    """
    return await api_tools.my_tool_implementation(param_one, param_two)
```

Guidelines:
- The docstring is shown verbatim in Claude Desktop / MCP Inspector — make it useful
- Always `async def` and return `str`
- Validate inputs early; raise `ValueError` for bad params
- Wrap all external calls in `try/except` and return a descriptive error string (never raise unhandled)
- Add the underlying implementation to `tools/api/tools.py`, not in `server.py`

---

## Adding a New MCP Prompt

Prompts are reusable workflow templates that guide an LLM through a multi-step task.

```python
@mcp_app.prompt()
def my_workflow(theme: str, style: str = "default") -> str:
    """
    One-line summary of the workflow.

    Args:
        theme: What the workflow is about
        style: Optional style hint
    """
    return f"""You are a Suno AI expert.

**Task:** …{theme}…

**Step 1 – …**
…

**Step 2 – …**
…

**Step N – Call the tool**
```
suno_api_generate(…)
```
"""
```

Guidelines:
- Prompts are **sync** (not async)
- Return a complete instruction string — the LLM receives this as its system context
- Use f-string interpolation for the user-supplied parameters
- Follow the two-field model: style tags (≤200 chars) + lyrics/prompt — see `suno://prompt-guide`

---

## Adding a New MCP Resource

Resources expose readable context (static reference data or live API data).

```python
# Static resource
@mcp_app.resource("suno://my-reference")
def resource_my_reference() -> str:
    """Short description shown in the inspector."""
    return """# My Reference

…markdown content…
"""

# Live / async resource
@mcp_app.resource("suno://my-live-data")
async def resource_my_live_data() -> str:
    """Live data fetched on every read."""
    try:
        result = await api_tools.fetch_something()
        return f"# My Live Data\n\n{result}"
    except Exception as e:
        return f"# My Live Data\n\nError: {e}"
```

Guidelines:
- URI convention: `suno://<noun>` (lowercase, hyphens)
- Return Markdown — MCP clients render it
- Static resources are sync; live resources are async
- Always include a fallback error message for live resources

---

## Code Standards

### Python
- Python 3.10+ syntax (union types as `X | Y`, `match` statements OK)
- Type-annotate all function signatures
- `async def` for anything that touches the network or filesystem
- No bare `except:` — always catch specific exceptions or at minimum `Exception as e`
- No comments that just narrate the code (`# increment counter`) — only explain non-obvious intent

### Type Checking
This project uses **basedpyright** in `standard` mode.

```bash
# Check types
basedpyright src/
```

Fix all `error`-level diagnostics before submitting a PR.  
`warning`-level issues should be addressed but will not block merge.

### Formatting
No formatter is enforced, but keep line length ≤100 and use consistent 4-space indentation.

---

## Testing

### Unit Tests (no network required)
```bash
pytest tests/unit/ -v
```

All external calls (httpx, playwright, keyring) must be mocked.  
Use `unittest.mock.AsyncMock` for async methods.

### Live Integration Tests (requires prior login)
```bash
# Authenticate first
python -c "
import asyncio
from suno_mcp.tools.api.tools import ApiSunoTools
asyncio.run(ApiSunoTools().browser_login())
"

# Then run
pytest tests/local/ -v -s
```

### Coverage
```bash
pytest tests/unit/ --cov=suno_mcp --cov-report=term-missing
```

Target: **≥80% line coverage** on `tools/shared/` modules.

### Test Structure
```
tests/
├── unit/
│   ├── test_api_client.py       # ApiClient mocked network calls
│   ├── test_api_tools.py        # ApiSunoTools method tests
│   ├── test_credentials.py      # Credential storage tests
│   ├── test_server_tools.py     # MCP tool registration tests
│   └── test_session_manager.py  # JWT decode / refresh tests
└── local/
    └── test_live_api.py         # End-to-end against real Suno API
```

---

## Branching & Commits

### Branches
| Pattern | Use |
|---------|-----|
| `main` | Stable, always deployable |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `chore/<name>` | Tooling, CI, dependencies |

### Conventional Commits
```
type(scope): short description

[optional body — explain WHY, not WHAT]

[optional footer — BREAKING CHANGE: …]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`

Examples:
```
feat(server): add suno_api_generate_stems tool
fix(credentials): handle DPAPI failure on first run gracefully
docs(readme): add Cursor integration example
```

---

## Pull Requests

1. Branch from `main`: `git checkout -b feat/my-feature`
2. Make your changes with tests
3. Run `pytest tests/unit/ -v` — all must pass
4. Run `basedpyright src/` — no new errors
5. Update `CHANGELOG.md` under `[Unreleased]`
6. Open a PR against `arlinamid/suno-mcp:main`
7. Fill in the PR template (what, why, how tested)

---

## Security

- **Never log credentials, tokens, or cookie values** — use fingerprints (`value[:8]…`)
- Session cookies go through `credentials.py` → OS keyring only
- Large values (> 1800 bytes) use DPAPI (Windows) or Fernet AES (macOS/Linux)
- No plaintext secrets in config files, environment variables, or test fixtures
- If you find a security issue, please open a **private** GitHub Security Advisory rather than a public issue

---

## Release Checklist

- [ ] `pytest tests/unit/ -v` passes
- [ ] `basedpyright src/` — no new errors
- [ ] `CHANGELOG.md` — new version section added
- [ ] Version bumped in `pyproject.toml` and `server.py` (4 occurrences)
- [ ] `README.md` — "Last updated" and "Version" lines updated
- [ ] `git tag v<X.Y.Z>` created
- [ ] GitHub Release published with changelog excerpt

### Versioning (SemVer)
| Change | Bump |
|--------|------|
| Breaking change to existing tool signature or behaviour | MAJOR |
| New tool / prompt / resource added | MINOR |
| Bug fix, typo, refactor with no API change | PATCH |

---

## Getting Help

- **Bug reports / feature requests** — [GitHub Issues](https://github.com/arlinamid/suno-mcp/issues)
- **Questions / ideas** — [GitHub Discussions](https://github.com/arlinamid/suno-mcp/discussions)
- Include: OS, Python version, error message + full traceback, steps to reproduce

---

## Code of Conduct

- Be respectful and constructive
- Welcome newcomers
- Keep feedback focused on the code, not the person
- Respect differing viewpoints and implementation choices

---

## License

By contributing you agree your changes will be released under the **MIT License**.
