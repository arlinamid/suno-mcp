import asyncio, re, httpx, sys
sys.path.insert(0, 'src')

async def find_advanced_params():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122"}
    TARGET_KEYS = ["weirdness", "style_influence", "vocal_gender", "lyrics_mode",
                   "style_strength", "seed", "history_continuation_influence",
                   "generation_quality", "vocal_strength"]
    
    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=15) as c:
        resp = await c.get("https://suno.com/create")
        js_urls = list(set(re.findall(r'/_next/static/chunks/[^"\'<>]+\.js', resp.text)))
        js_urls_sorted = sorted(js_urls, key=lambda u: 0 if 'app' in u else 1)

        found_keys = {}
        generate_bodies = []

        for url in js_urls_sorted[:80]:
            full = "https://suno.com" + url
            try:
                r = await c.get(full, timeout=8)
                t = r.text
                for key in TARGET_KEYS:
                    if key in t:
                        # Get context around key
                        idx = t.find(key)
                        context = t[max(0,idx-80):idx+120]
                        found_keys[key] = context.replace('\n', ' ')[:180]

                # Find generate/v2 request bodies
                if "generate/v2" in t or "generate/v3" in t:
                    # grab JSON-like structures around generate
                    blocks = re.findall(r'(?:generate|mv)[^;]{0,500}(?:chirp|crow)[^;]{0,200}', t)
                    generate_bodies.extend(blocks[:3])
            except Exception:
                pass

        print("Advanced parameter keys found:")
        for k, ctx in found_keys.items():
            print(f"\n  KEY: {k!r}")
            print(f"  CTX: {ctx}")

        if generate_bodies:
            print("\n\nGenerate request body context:")
            for b in generate_bodies[:3]:
                print(" ", b[:300])
                print()

asyncio.run(find_advanced_params())
