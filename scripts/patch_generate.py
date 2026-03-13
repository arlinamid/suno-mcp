"""Patch _generate_via_browser to use the opensuno token-extraction approach."""
import re

content = open('src/suno_mcp/tools/api/tools.py', encoding='utf-8').read()

# Find the section to replace using a unique anchor
ANCHOR_START = '            page = await context.new_page()\n\n            # Intercept /generate/v2-web/'
ANCHOR_END = '        return generate_response\n\n    async def api_extend_song('

start_idx = content.find(ANCHOR_START)
end_idx = content.find(ANCHOR_END)

if start_idx == -1 or end_idx == -1:
    print(f"ANCHOR_START found: {start_idx != -1}")
    print(f"ANCHOR_END found: {end_idx != -1}")
    raise SystemExit("Anchors not found!")

# Replace from ANCHOR_START to (not including) the api_extend_song def
new_block = '''            page = await context.new_page()
            await page.goto("https://suno.com/create", wait_until="networkidle")
            # Wait for Clerk + hCaptcha to initialize
            await asyncio.sleep(3)
            tokens = await page.evaluate(_GET_TOKENS_JS)
            await browser.close()

        captcha_token: str = tokens.get("captchaToken") or ""
        clerk_token: str = tokens.get("clerkToken") or ""

        self.logger.info(
            "Tokens -- captcha: %s  clerk JWT: %s",
            "OK" if captcha_token else "MISSING",
            "OK" if clerk_token else "MISSING",
        )

        if not captcha_token:
            raise SunoError(
                "hCaptcha token could not be obtained. "
                "Ensure you are logged into suno.com. "
                "Run suno_browser_login() to re-authenticate.",
                "CAPTCHA_FAILED"
            )

        import httpx as _httpx
        body: Dict[str, Any] = {
            "token": captcha_token,
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
            body["vocal_gender"] = vocal_gender
        if weirdness != 50:
            body["weirdness_constraint"] = weirdness
        if style_weight != 50:
            body["style_weight"] = style_weight

        client = get_api_client()
        auth_headers = client._get_auth_headers()
        if clerk_token:
            auth_headers["Authorization"] = f"Bearer {clerk_token}"

        async with _httpx.AsyncClient(
            timeout=_httpx.Timeout(30.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                ),
                "Origin": "https://suno.com",
                "Referer": "https://suno.com/create",
                **auth_headers,
            },
        ) as http:
            resp = await http.post(
                "https://studio-api.prod.suno.com/api/generate/v2-web/",
                json=body,
            )

        if resp.status_code != 200:
            raise SunoError(
                f"Generation failed ({resp.status_code}): {resp.text[:300]}",
                "GENERATE_API_ERROR"
            )

        return resp.json()

'''

new_content = content[:start_idx] + new_block + ANCHOR_END[len('        return generate_response\n\n'):]
# Hmm that's wrong. Let me just do it cleanly:
end_of_func = end_idx + len('        return generate_response\n')
new_content = content[:start_idx] + new_block.rstrip('\n') + '\n\n    async def api_extend_song(' + content[end_idx + len(ANCHOR_END):]

open('src/suno_mcp/tools/api/tools.py', 'w', encoding='utf-8').write(new_content)
print(f"PATCHED: replaced chars {start_idx}..{end_of_func}")
print("Verify by checking line count:", new_content.count('\n'), "lines")
