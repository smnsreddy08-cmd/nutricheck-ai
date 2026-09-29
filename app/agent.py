# Copyright 2026 Google LLC
# NutriCheck AI Agent with Firestore, GCS, Image Gen, Public APIs, Sandbox Code Execution, Memory Bank & A2UI v0.8 Integration

import io
import json
import os
import re
import urllib.parse
import urllib.request

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

from .a2ui_utils import a2ui_callback

# GCP Project constants for Firestore & Storage
FIRESTORE_PROJECT_ID = os.environ.get("FIRESTORE_PROJECT_ID", "productinfo-69d4c")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "nutricheck-ai-assets-qwiklabs-gcp-01-60ae6014122e")
MEMORY_BANK_ID = os.environ.get("MEMORY_BANK_ID", "7629148346300497920")

db = firestore.Client(project=FIRESTORE_PROJECT_ID)
storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
global_genai_client = genai.Client(
    vertexai=True, project=FIRESTORE_PROJECT_ID, location="global"
)

# Load Agent Engine resource name from deployment_metadata.json if available
deployment_metadata_path = os.path.join(
    os.path.dirname(__file__), "..", "deployment_metadata.json"
)
agent_engine_resource_name = None

if os.path.exists(deployment_metadata_path):
    try:
        with open(deployment_metadata_path, "r") as f:
            metadata = json.load(f)
            agent_engine_resource_name = metadata.get("remote_agent_runtime_id")
    except Exception:
        pass

# Initialize AgentEngineSandboxCodeExecutor for secure Agent Platform Python sandbox code execution
code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


# Memory service builder for deployed Agent Engine memory service
def memory_bank_service_builder():
    """Builds a VertexAiMemoryBankService instance pointed at the deployed Agent Engine Memory Bank."""
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


# Callback to extract session events into Vertex AI Memory Bank after each turn
async def generate_memories_callback(callback_context: CallbackContext):
    """Sends session turn history to Vertex AI Memory Bank for long-term fact extraction."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        print(f"Memory callback notice: {e}")
    return None


def generate_product_image(product_name: str, tool_context: ToolContext) -> str:
    """Generates an AI image for a food product or healthy snack item using gemini-3.1-flash-lite-image in the global region.

    Saves the image as a session artifact and uploads it to public Cloud Storage.

    Args:
        product_name: The food product or clean snack concept (e.g., 'healthy oat digestive cookie', 'dark chocolate avocado bowl').
        tool_context: ADK ToolContext used to save session artifacts for the Playground panel.

    Returns:
        The public HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated image.
    """
    try:
        prompt = f"A realistic high quality product packaging photo of a food item: {product_name}"

        response = global_genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
        )

        image_bytes = None
        mime_type = "image/jpeg"

        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break

        if not image_bytes:
            return f"Failed to generate image bytes for '{product_name}'."

        slug = re.sub(r"[^a-z0-9]", "-", product_name.lower()).strip("-")[:30] or "product"
        ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else "png"
        filename = f"{slug}.{ext}"

        # 1. Save with tool_context.save_artifact for Playground Artifacts panel
        if tool_context:
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload same image bytes to public Cloud Storage bucket
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob_name = f"generated_items/{filename}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob_name}"
        return f"Generated image successfully!\nPublic Image URL: {public_url}"
    except Exception as e:
        return f"Error generating product image: {e}"


def fetch_open_food_facts(product_name: str) -> str:
    """Queries the Open Food Facts international public API for real-time global nutrition, Nutri-Score grade, and NOVA processing group data.

    Args:
        product_name: Product title or brand to query on Open Food Facts (e.g. 'Oreo', 'KitKat', 'Doritos', 'Coca-Cola').

    Returns:
        Live global nutritional facts, Nutri-Score (A-E), NOVA group (1-4), sugar, fat, salt, and calories.
    """
    try:
        api_key = os.environ.get("OPEN_FOOD_FACTS_API_KEY", "")

        query_encoded = urllib.parse.quote(product_name.strip())
        url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={query_encoded}&search_simple=1&action=process&json=1&page_size=2"

        headers = {"User-Agent": "NutriCheckAI - Agent Platform - Python/3.11"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            products = data.get("products", [])

            if not products:
                return f"No live data found on Open Food Facts for '{product_name}'."

            p = products[0]
            nutriments = p.get("nutriments", {})
            nutriscore = str(p.get("nutriscore_grade", "N/A")).upper()
            nova = str(p.get("nova_group", "N/A"))
            additives_tags = p.get("additives_tags", [])

            return (
                f"🌐 **Open Food Facts Live Data for '{p.get('product_name', product_name)}'**:\n"
                f"• **Nutri-Score Grade**: {nutriscore}\n"
                f"• **NOVA Processing Group**: {nova} (Group 4 = Ultra-Processed Food)\n"
                f"• **Sugar per 100g**: {nutriments.get('sugars_100g', 'N/A')}g\n"
                f"• **Fat per 100g**: {nutriments.get('fat_100g', 'N/A')}g\n"
                f"• **Salt per 100g**: {nutriments.get('salt_100g', 'N/A')}g\n"
                f"• **Calories per 100g**: {nutriments.get('energy-kcal_100g', 'N/A')} kcal\n"
                f"• **E-number Additives**: {', '.join(additives_tags) or 'None listed'}"
            )
    except Exception as e:
        return f"Error fetching from Open Food Facts API: {e}"


def fetch_fruit_nutrition(fruit_name: str) -> str:
    """Queries the Fruityvice public REST API for natural fruit nutrition (calories, natural sugar, carbs, protein, fat) for clean food alternatives.

    Args:
        fruit_name: Name of the fruit to query (e.g., 'banana', 'apple', 'orange', 'strawberry', 'mango').

    Returns:
        Natural fruit nutritional breakdown.
    """
    try:
        api_key = os.environ.get("FRUITYVICE_API_KEY", "")
        name_clean = urllib.parse.quote(fruit_name.strip().lower())
        url = f"https://www.fruityvice.com/api/fruit/{name_clean}"

        headers = {"User-Agent": "NutriCheckAI/1.0"}
        if api_key:
            headers["X-Api-Key"] = api_key

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            nutr = data.get("nutritions", {})
            return (
                f"🍎 **Natural Fruit Nutrition for '{data.get('name', fruit_name)}'** (Fruityvice API):\n"
                f"• **Calories**: {nutr.get('calories', 'N/A')} kcal\n"
                f"• **Natural Sugar**: {nutr.get('sugar', 'N/A')}g\n"
                f"• **Carbohydrates**: {nutr.get('carbohydrates', 'N/A')}g\n"
                f"• **Protein**: {nutr.get('protein', 'N/A')}g\n"
                f"• **Fat**: {nutr.get('fat', 'N/A')}g"
            )
    except Exception as e:
        return f"Error querying Fruityvice API: {e}"


def get_product_nutrition(product_query: str) -> str:
    """Reads nutritional facts, raw ingredients, chemical additives (E-numbers/INS codes), and health scores for a food product from Firestore.

    Args:
        product_query: The product name or ID (e.g., 'oreo', 'maggi', 'kurkure', 'kitkat', 'coca-cola').

    Returns:
        A string containing the product's nutrition, raw ingredients, chemical additives, and health verdict if found in DB,
        or a notification instructing the agent to dynamically analyze and save unlisted products.
    """
    try:
        query_lower = product_query.strip().lower()
        collection_ref = db.collection("products")
        docs = collection_ref.stream()

        matched_products = []
        for doc in docs:
            data = doc.to_dict()
            prod_id = str(data.get("product_id", "")).lower()
            prod_name = str(data.get("name", "")).lower()
            prod_brand = str(data.get("brand", "")).lower()
            prod_category = str(data.get("category", "")).lower()

            if (
                query_lower in prod_id
                or query_lower in prod_name
                or query_lower in prod_brand
                or query_lower in prod_category
            ):
                matched_products.append(data)

        if not matched_products:
            return (
                f"STATUS: PRODUCT_NOT_IN_DB\n"
                f"Product '{product_query}' is not yet in the Firestore database. "
                f"Please dynamically estimate/analyze its nutritional values, ingredients, E-number/INS chemical additives, "
                f"and Health Score (0-100), answer the user, AND call `save_product_nutrition` to store it in Firestore for future queries."
            )

        results = []
        for p in matched_products:
            chems = p.get("chemical_additives", [])
            chems_str = ", ".join(chems) if chems else "None / Zero synthetic chemical additives"

            results.append(
                f"[Source: Firestore Database Cache]\n"
                f"--- {p.get('name')} ---\n"
                f"Product ID: {p.get('product_id')}\n"
                f"Brand: {p.get('brand')} | Category: {p.get('category', 'Packaged Food')}\n"
                f"Pack Size: {p.get('pack_size_grams')}g | Price: ₹{p.get('price_inr')}\n"
                f"Sugar: {p.get('sugar_grams')}g | Fat: {p.get('fat_grams')}g | Protein: {p.get('protein_grams')}g | Sodium: {p.get('sodium_mg')}mg\n"
                f"Raw Ingredients: {', '.join(p.get('ingredients', []))}\n"
                f"Chemical Additives & Preservatives: {chems_str}\n"
                f"Overall Health Score: {p.get('health_score')}/100\n"
                f"Verdict: {p.get('health_verdict')}"
            )
        return "\n\n".join(results)
    except Exception as e:
        return f"Error accessing Firestore database: {e}"


def save_product_nutrition(
    product_id: str,
    name: str,
    brand: str,
    category: str,
    pack_size_grams: float,
    price_inr: float,
    sugar_grams: float,
    fat_grams: float,
    protein_grams: float,
    sodium_mg: float,
    ingredients: str,
    chemical_additives: str,
    health_score: int,
    health_verdict: str,
) -> str:
    """Saves or updates a food product's nutrition, ingredient, chemical additives, and health details in Firestore.

    Args:
        product_id: Unique lowercase slug for the product (e.g., 'kitkat-4-finger-38g').
        name: Full product title (e.g., 'Nestlé KitKat 4 Finger Pack').
        brand: Brand or manufacturer (e.g., 'Nestlé').
        category: Food category (e.g., 'Chocolates & Confectionery', 'Beverages', 'Snacks').
        pack_size_grams: Weight/volume of pack in grams or ml.
        price_inr: Price in INR (₹).
        sugar_grams: Sugar content in grams.
        fat_grams: Total fat in grams.
        protein_grams: Protein content in grams.
        sodium_mg: Sodium in milligrams.
        ingredients: Comma-separated string of raw ingredients.
        chemical_additives: Comma-separated string of INS codes / E-numbers / chemical additives.
        health_score: Overall Health Score from 0 to 100.
        health_verdict: Detailed breakdown of sugar, palm oil, and health advice.

    Returns:
        Confirmation message upon saving to Firestore.
    """
    try:
        doc_ref = db.collection("products").document(product_id)
        data = {
            "product_id": product_id,
            "name": name,
            "brand": brand,
            "category": category,
            "pack_size_grams": pack_size_grams,
            "price_inr": price_inr,
            "sugar_grams": sugar_grams,
            "fat_grams": fat_grams,
            "protein_grams": protein_grams,
            "sodium_mg": sodium_mg,
            "ingredients": [i.strip() for i in ingredients.split(",") if i.strip()],
            "chemical_additives": [c.strip() for c in chemical_additives.split(",") if c.strip()],
            "health_score": health_score,
            "health_verdict": health_verdict,
        }
        doc_ref.set(data, merge=True)
        return f"Successfully cached product '{name}' (ID: {product_id}) into Firestore database."
    except Exception as e:
        return f"Error saving product to Firestore: {e}"


def list_products() -> str:
    """Lists all food products currently stored in the Firestore database.

    Returns:
        A list of available products with their IDs and health scores.
    """
    try:
        collection_ref = db.collection("products")
        docs = collection_ref.stream()
        items = []
        for doc in docs:
            p = doc.to_dict()
            items.append(
                f"• {p.get('name')} (ID: {p.get('product_id')}) - Category: {p.get('category', 'N/A')} - Health Score: {p.get('health_score')}/100"
            )
        if not items:
            return "No products found in Firestore database."
        return f"Total Products in Firestore ({len(items)} items):\n" + "\n".join(items)
    except Exception as e:
        return f"Error listing products from Firestore: {e}"


def search_clean_alternatives(
    category_or_product_name: str, max_sugar_grams: float = 10.0
) -> str:
    """Tool 1: Searches the Firestore database for healthier food alternatives that have a high Health Score (>= 60) and lower sugar.

    Args:
        category_or_product_name: Category or product name to find healthy alternatives for (e.g., 'biscuits', 'cookies', 'snacks', 'oreo', 'chips').
        max_sugar_grams: Maximum acceptable sugar in grams for recommended alternatives (default 10.0g).

    Returns:
        A formatted list of healthier substitute options with high health scores and cleaner ingredients.
    """
    try:
        query = category_or_product_name.strip().lower()
        collection_ref = db.collection("products")
        docs = collection_ref.stream()

        clean_options = []
        for doc in docs:
            p = doc.to_dict()
            score = int(p.get("health_score", 0))
            sugar = float(p.get("sugar_grams", 0.0))

            if score >= 55 and sugar <= max_sugar_grams:
                clean_options.append(p)

        clean_options.sort(key=lambda x: x.get("health_score", 0), reverse=True)

        if not clean_options:
            return f"No healthier alternatives currently in database with sugar <= {max_sugar_grams}g and Health Score >= 55."

        output = [f"🌱 **Recommended Healthier Alternatives for '{category_or_product_name}'**:\n"]
        for p in clean_options[:3]:
            output.append(
                f"✅ **{p.get('name')}** (Brand: {p.get('brand')})\n"
                f"   • **Health Score**: {p.get('health_score')}/100\n"
                f"   • **Sugar**: {p.get('sugar_grams')}g | **Fat**: {p.get('fat_grams')}g | **Protein**: {p.get('protein_grams')}g\n"
                f"   • **Key Ingredients**: {', '.join(p.get('ingredients', []))[:100]}\n"
                f"   • **Why it's better**: {p.get('health_verdict')}\n"
            )

        return "\n".join(output)
    except Exception as e:
        return f"Error searching clean alternatives: {e}"


def calculate_personalized_rda_impact(
    product_query: str,
    is_diabetic: bool = False,
    is_hypertensive: bool = False,
    serving_packs: float = 1.0,
) -> str:
    """Tool 2: Computes the exact percentage of Recommended Daily Allowance (RDA) consumed for sugar, sodium, and fat, with custom health condition warnings.

    Args:
        product_query: Product name or ID (e.g. 'oreo', 'maggi', 'lays').
        is_diabetic: Set to True if user is diabetic or pre-diabetic (stricter 10g sugar limit).
        is_hypertensive: Set to True if user has high blood pressure (stricter 1500mg sodium limit).
        serving_packs: Number of packs consumed (default 1.0).

    Returns:
        Detailed RDA percentage breakdown and specific medical risk warnings.
    """
    try:
        STANDARD_SUGAR_LIMIT_G = 25.0
        DIABETIC_SUGAR_LIMIT_G = 10.0

        STANDARD_SODIUM_LIMIT_MG = 2000.0
        HYPERTENSIVE_SODIUM_LIMIT_MG = 1500.0

        STANDARD_FAT_LIMIT_G = 20.0

        query_lower = product_query.strip().lower()
        collection_ref = db.collection("products")
        docs = collection_ref.stream()

        product = None
        for doc in docs:
            data = doc.to_dict()
            if (
                query_lower in str(data.get("product_id", "")).lower()
                or query_lower in str(data.get("name", "")).lower()
            ):
                product = data
                break

        if not product:
            sugar_g = 16.5 * serving_packs
            sodium_mg = 300.0 * serving_packs
            fat_g = 9.0 * serving_packs
            prod_name = product_query
        else:
            sugar_g = float(product.get("sugar_grams", 0.0)) * serving_packs
            sodium_mg = float(product.get("sodium_mg", 0.0)) * serving_packs
            fat_g = float(product.get("fat_grams", 0.0)) * serving_packs
            prod_name = product.get("name")

        sugar_limit = DIABETIC_SUGAR_LIMIT_G if is_diabetic else STANDARD_SUGAR_LIMIT_G
        sodium_limit = HYPERTENSIVE_SODIUM_LIMIT_MG if is_hypertensive else STANDARD_SODIUM_LIMIT_MG

        sugar_rda_pct = (sugar_g / sugar_limit) * 100.0
        sodium_rda_pct = (sodium_mg / sodium_limit) * 100.0
        fat_rda_pct = (fat_g / STANDARD_FAT_LIMIT_G) * 100.0
        teaspoons_sugar = sugar_g / 4.0

        lines = [
            f"📊 **Personalized RDA Breakdown for '{prod_name}' ({serving_packs} pack(s))**:",
            f"• **Sugar Consumed**: {sugar_g:.1f}g (~{teaspoons_sugar:.1f} teaspoons of sugar)",
            f"  - **RDA Impact**: **{sugar_rda_pct:.1f}%** of daily limit ({'⚠️ DIABETIC DANGER ZONE!' if is_diabetic and sugar_rda_pct > 50 else 'High Sugar'})",
            f"• **Sodium (Salt)**: {sodium_mg:.0f}mg",
            f"  - **RDA Impact**: **{sodium_rda_pct:.1f}%** of daily limit ({'⚠️ HIGH BLOOD PRESSURE RISK!' if is_hypertensive and sodium_rda_pct > 30 else 'Sodium Level'})",
            f"• **Total Fat**: {fat_g:.1f}g",
            f"  - **RDA Impact**: **{fat_rda_pct:.1f}%** of daily saturated fat limit",
        ]

        if is_diabetic and sugar_g > 5.0:
            lines.append("\n🚨 **Medical Risk Flag (Diabetic)**: This product contains significant fast-acting refined sugar that can cause rapid blood glucose spikes.")
        if is_hypertensive and sodium_mg > 400.0:
            lines.append("\n🚨 **Medical Risk Flag (Hypertension)**: High sodium intake elevates arterial pressure.")

        return "\n".join(lines)
    except Exception as e:
        return f"Error calculating personalized RDA impact: {e}"


def generate_nutrition_warning_seal(
    product_name: str, health_score: int, sugar_grams: float, sodium_mg: float
) -> str:
    """Tool 3: Generates a visual Health Warning Seal badge image, uploads it to Google Cloud Storage, and returns the public image URL.

    Args:
        product_name: Name of the food product (e.g., 'Oreo Biscuits ₹10 Pack').
        health_score: Health score 0-100.
        sugar_grams: Sugar in grams.
        sodium_mg: Sodium in milligrams.

    Returns:
        Public HTTP URL of the generated PNG graphic seal stored in Cloud Storage.
    """
    try:
        img = Image.new("RGB", (400, 400), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        if health_score >= 70:
            bg_color = (46, 125, 50)
            verdict_text = "HEALTHY CHOICE"
        elif health_score >= 50:
            bg_color = (245, 127, 23)
            verdict_text = "MODERATE RISK"
        else:
            bg_color = (198, 40, 40)
            verdict_text = "HIGH HEALTH RISK"

        draw.rectangle([(0, 0), (400, 70)], fill=bg_color)
        draw.text((20, 20), "NUTRICHECK AI SEAL", fill=(255, 255, 255))

        draw.ellipse([(100, 90), (300, 290)], fill=bg_color, outline=(200, 200, 200), width=4)
        draw.text((150, 150), f"{health_score}/100", fill=(255, 255, 255))
        draw.text((130, 210), verdict_text, fill=(255, 255, 255))

        teaspoons = sugar_grams / 4.0
        draw.text((30, 310), f"Product: {product_name[:30]}", fill=(0, 0, 0))
        draw.text((30, 335), f"Sugar: {sugar_grams}g (~{teaspoons:.1f} tsp sugar)", fill=(198, 40, 40))
        draw.text((30, 360), f"Sodium: {sodium_mg}mg", fill=(0, 0, 0))

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        slug = re.sub(r"[^a-z0-9]", "-", product_name.lower()).strip("-")[:30]
        blob_name = f"seals/{slug}_seal.png"
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(buffer.getvalue(), content_type="image/png")

        public_url = f"https://storage.googleapis.com/nutricheck-ai-assets-qwiklabs-gcp-01-60ae6014122e/{blob_name}"
        return f"Generated Health Seal Graphic!\nPublic Image URL: {public_url}"
    except Exception as e:
        return f"Error generating nutrition seal graphic: {e}"


# Build A2UI v0.8 system prompt with BasicCatalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are NutriCheck AI, an expert food reality and nutritional transparency assistant for Indian packaged foods. "
        "Your mission is to uncover the truth behind any food product a user asks about, revealing hidden sugar/salt/palm oil reality, "
        "exposing chemical additives (INS codes / E-numbers) and harmful health effects, calculating personalized RDA impact, and recommending clean food alternatives."
    ),
    workflow_description=(
        "1. When a user asks about a packaged food or drink (e.g. Oreo, Maggi, KitKat, Coca-Cola, Kurkure, Lay's, etc.), ALWAYS first call `get_product_nutrition`.\n"
        "2. If `get_product_nutrition` returns 'PRODUCT_NOT_IN_DB', call `fetch_open_food_facts` to pull live international Nutri-Score/NOVA data, analyze the product, call `save_product_nutrition` to store it in Firestore, and proceed.\n"
        "3. Provide a clear breakdown including: ⚠️ Product Reality & Nutritional Summary, 🧪 Chemicals & Additives Used & Harmful Health Effects, 🎯 Perfect Health Score (0-100) & Transparent Scoring Breakdown, 🍪 Visual Health Warning Seal (via `generate_nutrition_warning_seal`), and 🌱 Healthier Alternatives (via `search_clean_alternatives` or `fetch_fruit_nutrition`).\n"
        "4. Use `PreloadMemoryTool` to check saved user health profiles (e.g. diabetes, hypertension).\n"
        "5. Use Python code execution for complex percentage RDA calculations."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use Table or Heading. "
        "You may include one Image component when you have a public https URL (e.g. from generate_nutrition_warning_seal or generate_product_image). "
        "No markdown in text; use usageHint ('h1', 'h2', 'body') for headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in <a2a_datapart_json> tags."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        get_product_nutrition,
        save_product_nutrition,
        list_products,
        search_clean_alternatives,
        calculate_personalized_rda_impact,
        generate_nutrition_warning_seal,
        fetch_open_food_facts,
        fetch_fruit_nutrition,
        generate_product_image,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
