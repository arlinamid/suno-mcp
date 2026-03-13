"""
Intercept the actual POST /generate/v2/ request body from suno.com
by using an existing session and capturing the network traffic.
"""
import asyncio, json, sys
sys.path.insert(0, 'src')

from suno_mcp.tools.shared.credentials import get_credential_store
from suno_mcp.tools.shared.session_manager import cookies_from_playwright

async def intercept():
    from playwright.async_api import async_playwright

    creds = get_credential_store()
    existing_jar = creds.get_cookie_jar()

    generate_requests = []
    generate_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145"
        )

        # Pre-load session cookies
        if existing_jar:
            pw_cookies = [
                {"name": k, "value": v, "domain": ".suno.com", "path": "/",
                 "secure": True, "httpOnly": k in ("__client",), "sameSite": "Lax"}
                for k, v in existing_jar.items()
            ]
            await context.add_cookies(pw_cookies)

        page = await context.new_page()

        # Intercept requests
        async def on_request(req):
            if "generate/v2" in req.url and req.method == "POST":
                raw = req.post_data or ""
                print("\n=== GENERATE REQUEST URL ===", req.url)
                print("=== GENERATE REQUEST BODY (full) ===")
                print(raw)  # no truncation
                try:
                    body = json.loads(raw)
                    generate_requests.append(body)
                    print("=== PARSED KEYS ===", list(body.keys()))
                except Exception as e:
                    generate_requests.append({"raw": raw})
                    print("(parse error:", e, ")")

        async def on_response(resp):
            if "generate/v2" in resp.url:
                try:
                    body = await resp.json()
                    generate_responses.append(body)
                    print("\n=== GENERATE RESPONSE ===")
                    print(json.dumps(body, indent=2)[:600])
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto("https://suno.com/create", wait_until="domcontentloaded")
        print("Browser open. Please click 'Create' once to generate a test song.")
        print("Press Ctrl+C when done or wait 120s...")

        try:
            await asyncio.sleep(120)
        except KeyboardInterrupt:
            pass

        await browser.close()

    if not generate_requests:
        print("\nNo generate requests captured.")

asyncio.run(intercept())
