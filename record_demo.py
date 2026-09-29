import asyncio
import os
import shutil
from playwright.async_api import async_playwright

VIDEO_DIR = "/config/.gemini/antigravity/brain/7513cf35-e252-4ca5-ba5f-8c215722c0e1/demo_video"
OUTPUT_VIDEO_PATH = "/config/.gemini/antigravity/brain/7513cf35-e252-4ca5-ba5f-8c215722c0e1/nutricheck_ai_demo.mp4"

os.makedirs(VIDEO_DIR, exist_ok=True)

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        
        print("Navigating to NutriCheck AI web application...")
        await page.goto("http://localhost:8080", wait_until="networkidle")
        await asyncio.sleep(2)
        
        print("Prompt 1: Asking about Oreo Biscuits 10 pack...")
        input_el = page.locator("form input")
        await input_el.fill("Is Oreo Biscuits 10 pack healthy or full of sugar?")
        await asyncio.sleep(1)
        await page.locator("form button[type='submit']").click()
        
        print("Waiting for response to Prompt 1...")
        for _ in range(30):
            await asyncio.sleep(1)
            text = await page.locator("#log").inner_text()
            if "Sugar" in text or "Unhealthy" in text or "Nutritional" in text or "Oreo" in text or "Error" in text:
                if "Analyzing" not in text:
                    break
        
        await asyncio.sleep(4)
        
        print("Prompt 2: Asking rich prompt (database search clean alternatives & image generation warning seal)...")
        await input_el.fill("Search Firestore for clean healthy biscuit alternatives and generate a visual health warning seal image for Oreo Biscuits.")
        await asyncio.sleep(1)
        await page.locator("form button[type='submit']").click()
        
        print("Waiting for response to Prompt 2...")
        for _ in range(40):
            await asyncio.sleep(1)
            text = await page.locator("#log").inner_text()
            if "storage.googleapis.com" in text or "Warning Seal" in text or "Health Score" in text or "Error" in text:
                if text.count("bubble") > 3 or "Analyzing" not in text:
                    break
                
        await asyncio.sleep(8)
        
        print("Closing context to save video...")
        await page.close()
        await context.close()
        await browser.close()
        
        files = [os.path.join(VIDEO_DIR, f) for f in os.listdir(VIDEO_DIR) if f.endswith(".webm")]
        if files:
            rec_file = files[0]
            print(f"Recorded video file: {rec_file}")
            shutil.copy(rec_file, OUTPUT_VIDEO_PATH)
            shutil.copy(rec_file, OUTPUT_VIDEO_PATH.replace(".mp4", ".webm"))
            print(f"Saved demo video to {OUTPUT_VIDEO_PATH}")
        else:
            print("No video recorded!")

if __name__ == "__main__":
    asyncio.run(run())
