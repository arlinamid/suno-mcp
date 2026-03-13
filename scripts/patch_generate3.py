"""
Patch _generate_via_browser to use exact Advanced-mode selectors provided by user:
- lyrics textarea  (CSS path confirmed)
- style textarea   (CSS path confirmed)
- Male/Female buttons
- Weirdness slider [role=slider][aria-label="Weirdness"]
- Style Influence slider [role=slider][aria-label="Style Influence"]
- Song Title input (5th section)
"""

content = open('src/suno_mcp/tools/api/tools.py', encoding='utf-8').read()

func_start = content.find('    async def _generate_via_browser(')
next_def   = content.find('\n    async def ', func_start + 10)

NEW_FUNC = '''    async def _generate_via_browser(
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
        Browser-assisted generation (route-intercept + Advanced-mode UI filling).

        Flow:
          1. Open suno.com/create in Advanced mode with session cookies
          2. Fill Lyrics + Style textareas (enables Create button; exact selectors used)
          3. Set Vocal Gender button if requested
          4. Set Weirdness + Style Influence sliders via keyboard
          5. Fill Song Title field
          6. Route-intercept /generate/v2-web/ to inject our REAL params
             (including weirdness_constraint, style_weight, vocal_gender at top level)
          7. Capture response clip IDs, close browser
        Browser window visible ~15s, closes automatically.
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

        # Exact Advanced-mode selectors (confirmed by DOM inspection)
        SEL_LYRICS  = "#main-container div.card-popout-boundary div.css-js3s1x div:nth-child(2) textarea"
        SEL_STYLE   = "#main-container div.card-popout-boundary div.css-js3s1x div:nth-child(3) textarea"
        SEL_WEIRDNESS = "[role=\'slider\'][aria-label=\'Weirdness\']"
        SEL_STYLE_INF = "[role=\'slider\'][aria-label=\'Style Influence\']"
        SEL_TITLE   = "#main-container div.card-popout-boundary div.css-js3s1x div:nth-child(5) input"
        SEL_CREATE  = "button[aria-label=\'Create song\']"

        async with async_playwright() as p:
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
            if existing_jar:
                await context.add_cookies([
                    {"name": k, "value": v, "domain": ".suno.com", "path": "/",
                     "secure": True, "httpOnly": k == "__client", "sameSite": "Lax"}
                    for k, v in existing_jar.items()
                ])

            page = await context.new_page()

            # Route intercept: keep hCaptcha token, inject our real params
            async def handle_generate(route, request):
                try:
                    original = json.loads(request.post_data or "{}")
                    try:
                        clerk_jwt = await page.evaluate(
                            "async () => { const c = window.Clerk; "
                            "return c?.session ? await c.session.getToken() : null; }"
                        )
                    except Exception:
                        clerk_jwt = None

                    new_body: Dict[str, Any] = {
                        "token": original.get("token", ""),
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
                    if vocal_gender in ("male", "female"):
                        new_body["vocal_gender"] = vocal_gender
                    if weirdness != 50:
                        new_body["weirdness_constraint"] = weirdness
                    if style_weight != 50:
                        new_body["style_weight"] = style_weight

                    req_headers = dict(request.headers)
                    if clerk_jwt:
                        req_headers["authorization"] = f"Bearer {clerk_jwt}"
                    req_headers["content-type"] = "application/json"

                    self.logger.info(
                        "Intercepting generate -> model=%s  prompt=%d chars  weirdness=%s  style_weight=%s  vocal=%s",
                        mv, len(prompt), weirdness, style_weight, vocal_gender or "auto"
                    )
                    await route.continue_(post_data=json.dumps(new_body), headers=req_headers)
                except Exception as e:
                    self.logger.warning("Route intercept error: %s", e)
                    await route.continue_()

            await page.route("**/generate/v2-web/**", handle_generate)

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

            # Ensure Advanced mode is active
            try:
                await page.locator("button:has-text(\'Advanced\')").first.click(timeout=4000)
                await asyncio.sleep(0.8)
            except Exception:
                pass  # Already in Advanced mode

            # ── Fill Lyrics textarea ──────────────────────────────────────────────
            try:
                lyr = page.locator(SEL_LYRICS).first
                await lyr.wait_for(state="visible", timeout=6000)
                await lyr.click()
                await page.keyboard.press("Control+a")
                # Type up to 120 chars of the prompt (enough to enable Create btn)
                await lyr.press_sequentially((prompt or "test")[:120], delay=6)
                self.logger.info("Filled lyrics (%d chars shown)", min(len(prompt), 120))
            except Exception as e:
                self.logger.warning("Lyrics fill failed: %s", e)

            # ── Fill Style textarea ───────────────────────────────────────────────
            try:
                sty = page.locator(SEL_STYLE).first
                await sty.wait_for(state="visible", timeout=4000)
                await sty.click()
                await page.keyboard.press("Control+a")
                await sty.press_sequentially((tags or "pop")[:60], delay=5)
                self.logger.info("Filled style tags")
            except Exception as e:
                self.logger.warning("Style fill failed: %s", e)

            # ── Vocal Gender buttons ──────────────────────────────────────────────
            if vocal_gender in ("male", "female"):
                btn_text = "Male" if vocal_gender == "male" else "Female"
                try:
                    gender_btn = page.locator(f"button:has-text(\'{btn_text}\')").first
                    await gender_btn.wait_for(state="visible", timeout=3000)
                    await gender_btn.click()
                    self.logger.info("Set vocal gender: %s", vocal_gender)
                except Exception as e:
                    self.logger.debug("Gender button not found: %s (set in body)", e)

            # ── Weirdness slider ─────────────────────────────────────────────────
            if weirdness != 50:
                try:
                    slider = page.locator(SEL_WEIRDNESS).first
                    await slider.wait_for(state="visible", timeout=3000)
                    await slider.focus()
                    # Arrow keys: each press moves +1/-1 on 0-100 scale
                    # From 50, calculate delta
                    delta = weirdness - 50
                    key = "ArrowRight" if delta > 0 else "ArrowLeft"
                    for _ in range(abs(delta)):
                        await page.keyboard.press(key)
                    self.logger.info("Set Weirdness slider to %d", weirdness)
                except Exception as e:
                    self.logger.debug("Weirdness slider: %s (set in body)", e)

            # ── Style Influence slider ────────────────────────────────────────────
            if style_weight != 50:
                try:
                    slider = page.locator(SEL_STYLE_INF).first
                    await slider.wait_for(state="visible", timeout=3000)
                    await slider.focus()
                    delta = style_weight - 50
                    key = "ArrowRight" if delta > 0 else "ArrowLeft"
                    for _ in range(abs(delta)):
                        await page.keyboard.press(key)
                    self.logger.info("Set Style Influence slider to %d", style_weight)
                except Exception as e:
                    self.logger.debug("Style Influence slider: %s (set in body)", e)

            # ── Song Title ────────────────────────────────────────────────────────
            if title:
                try:
                    title_el = page.locator(SEL_TITLE).first
                    await title_el.wait_for(state="visible", timeout=3000)
                    await title_el.click()
                    await page.keyboard.press("Control+a")
                    await title_el.press_sequentially(title, delay=5)
                    self.logger.info("Filled song title: %s", title)
                except Exception as e:
                    self.logger.debug("Title field: %s (set in body)", e)

            # ── Create button ─────────────────────────────────────────────────────
            create_btn = page.locator(SEL_CREATE).first
            await create_btn.wait_for(state="visible", timeout=8000)
            for i in range(20):
                if not await create_btn.is_disabled():
                    self.logger.info("Create button enabled after %ds", i)
                    break
                await asyncio.sleep(1)
            else:
                self.logger.warning("Create button still disabled after 20s -- clicking anyway")

            try:
                await create_btn.click(timeout=5000)
            except Exception:
                await create_btn.click(force=True, timeout=5000)
            self.logger.info("Clicked Create button -- waiting for API response")

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

new_content = content[:func_start] + NEW_FUNC + content[next_def + 1:]
open('src/suno_mcp/tools/api/tools.py', 'w', encoding='utf-8').write(new_content)
print(f"Patched: {new_content.count(chr(10))} lines total")
