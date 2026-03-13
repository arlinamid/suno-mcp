"""Rewrite _generate_via_browser to clean route-intercept approach."""

content = open('src/suno_mcp/tools/api/tools.py', encoding='utf-8').read()

# Find the function start and end
func_start = content.find('    async def _generate_via_browser(')
# Find the NEXT async def after it
next_def = content.find('\n    async def ', func_start + 10)
print(f"Function: lines {content[:func_start].count(chr(10))+1} to {content[:next_def].count(chr(10))+1}")

new_func = '''    async def _generate_via_browser(
        self,
        prompt: str,
        tags: str,
        title: str,
        make_instrumental: bool,
        mv: str,
        negative_tags: str = "",
        vocal_gender: Optional[str] = None,
        weirdness: int = 50,
        style_weight: int = 50,
    ) -> Dict[str, Any]:
        """
        Browser-assisted generation using hCaptcha route-intercept technique.
        Inspired by opensuno (paean-ai/opensuno):
          1. Open suno.com/create with pre-loaded session cookies
          2. Switch to Advanced mode, type a single char to enable the Create button
          3. Set up page.route() to intercept /generate/v2-web/:
             - Keep the real hCaptcha token the browser obtained
             - Replace ALL content fields with our actual parameters
          4. Click Create -> hCaptcha auto-solves -> route intercept fires
          5. Capture response clip IDs, close browser
        The window is visible for ~15s and closes automatically.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise SunoError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium",
                "PLAYWRIGHT_MISSING"
            )

        creds = get_credential_store()
        existing_jar = creds.get_cookie_jar()
        import uuid as _uuid

        generate_response: Dict[str, Any] = {}
        request_ready = asyncio.Event()

        async with async_playwright() as p:
            # headless=False required: hCaptcha fingerprints headless browsers.
            # Window auto-closes after clips are submitted (~15s total).
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                )
            )

            # Pre-load all stored session cookies
            if existing_jar:
                await context.add_cookies([
                    {"name": k, "value": v, "domain": ".suno.com", "path": "/",
                     "secure": True, "httpOnly": k == "__client", "sameSite": "Lax"}
                    for k, v in existing_jar.items()
                ])

            page = await context.new_page()

            # Route intercept: keep hCaptcha token, replace all content with our params
            async def handle_generate(route, request):
                try:
                    original = json.loads(request.post_data or "{}")
                    # Extract fresh Clerk JWT while we have the page open
                    try:
                        clerk_jwt = await page.evaluate(
                            "async () => { const c = window.Clerk; "
                            "return c?.session ? await c.session.getToken() : null; }"
                        )
                    except Exception:
                        clerk_jwt = None

                    new_body: Dict[str, Any] = {
                        "token": original.get("token", ""),   # hCaptcha token -- keep!
                        "generation_type": "TEXT",
                        "prompt": prompt,
                        "tags": tags,
                        "negative_tags": negative_tags or "",
                        "title": title,
                        "make_instrumental": make_instrumental,
                        "mv": mv,
                        "transaction_uuid": str(_uuid.uuid4()),
                        "continue_clip_id": None,
                        "continue_at": None,
                        "user_uploaded_images_b64": None,
                        "override_fields": [],
                        "cover_clip_id": None,
                        "cover_start_s": None,
                        "cover_end_s": None,
                        "persona_id": None,
                        "artist_clip_id": None,
                        "artist_start_s": None,
                        "artist_end_s": None,
                        "metadata": {
                            "web_client_pathname": "/create",
                            "is_max_mode": False,
                            "is_mumble": False,
                            "create_mode": "custom",
                            "create_session_token": str(_uuid.uuid4()),
                            "disable_volume_normalization": False,
                        },
                    }
                    # Advanced options at top level
                    if vocal_gender in ("male", "female"):
                        new_body["vocal_gender"] = vocal_gender
                    if weirdness != 50:
                        new_body["weirdness_constraint"] = weirdness
                    if style_weight != 50:
                        new_body["style_weight"] = style_weight

                    # Use fresh Clerk JWT if available
                    req_headers = dict(request.headers)
                    if clerk_jwt:
                        req_headers["authorization"] = f"Bearer {clerk_jwt}"
                    req_headers["content-type"] = "application/json"

                    self.logger.info(
                        "Intercepted generate request -- replacing body (model=%s, prompt=%d chars)",
                        mv, len(prompt)
                    )
                    await route.continue_(post_data=json.dumps(new_body), headers=req_headers)
                except Exception as e:
                    self.logger.warning("Route intercept error: %s", e)
                    await route.continue_()

            await page.route("**/generate/v2-web/**", handle_generate)

            # Capture the response
            async def on_response(resp):
                if "generate/v2-web" in resp.url and resp.status == 200:
                    try:
                        data = await resp.json()
                        generate_response.update(data)
                        request_ready.set()
                    except Exception:
                        pass

            page.on("response", on_response)

            await page.goto("https://suno.com/create", wait_until="networkidle")
            await asyncio.sleep(2)

            # Switch to Advanced mode
            try:
                await page.locator("button:has-text('Advanced')").first.click(timeout=4000)
                await asyncio.sleep(0.8)
            except Exception:
                pass

            # Type a single character into the lyrics field to enable the Create button
            # (we don't need real content -- route intercept replaces it all)
            try:
                lyrics = page.locator("textarea[placeholder*='lyrics or a prompt']").first
                await lyrics.wait_for(state="visible", timeout=6000)
                await lyrics.click()
                await lyrics.press_sequentially("a", delay=50)
            except Exception as e:
                self.logger.warning("Could not enable Create button via lyrics: %s", e)

            # Wait for Create button to enable
            create_btn = page.locator("button[aria-label='Create song']").first
            await create_btn.wait_for(state="visible", timeout=8000)
            for _ in range(15):
                if not await create_btn.is_disabled():
                    break
                await asyncio.sleep(1)

            await create_btn.click()
            self.logger.info("Clicked Create song button -- waiting for API response")

            # Wait for generate response (up to 30s)
            try:
                await asyncio.wait_for(request_ready.wait(), timeout=30)
            except asyncio.TimeoutError:
                self.logger.warning("Generate response timed out after 30s")

            await browser.close()

        if not generate_response:
            raise SunoError(
                "Generation did not complete. Session may be expired. "
                "Run suno_browser_login() to re-authenticate.",
                "GENERATE_TIMEOUT"
            )

        return generate_response

'''

new_content = content[:func_start] + new_func + content[next_def + 1:]
open('src/suno_mcp/tools/api/tools.py', 'w', encoding='utf-8').write(new_content)
print(f"Written {len(new_content)} chars, {new_content.count(chr(10))} lines")
