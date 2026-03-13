"""Find the exact Create button selector on suno.com/create"""
import asyncio, sys, json
sys.path.insert(0, 'src')
from suno_mcp.tools.shared.credentials import get_credential_store
from playwright.async_api import async_playwright

async def main():
    creds = get_credential_store()
    jar = creds.get_cookie_jar()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145")
        if jar:
            await context.add_cookies([
                {"name": k, "value": v, "domain": ".suno.com", "path": "/",
                 "secure": True, "httpOnly": k == "__client", "sameSite": "Lax"}
                for k, v in jar.items()
            ])
        page = await context.new_page()
        await page.goto("https://suno.com/create", wait_until="networkidle")
        await asyncio.sleep(3)

        # Dump all buttons
        buttons = await page.evaluate("""
            () => Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.textContent.trim().slice(0,50),
                type: b.type,
                disabled: b.disabled,
                className: b.className.slice(0,80),
                id: b.id,
                ariaLabel: b.getAttribute('aria-label'),
                role: b.getAttribute('role'),
            }))
        """)
        print("All buttons on page:")
        for b in buttons:
            print(" ", json.dumps(b))

        # Take screenshot
        await page.screenshot(path="scripts/create_page.png")
        print("\nScreenshot saved to scripts/create_page.png")

        await browser.close()

asyncio.run(main())
