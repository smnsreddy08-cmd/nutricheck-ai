# NutriCheck AI — Complete End-to-End System Replication Guide

This guide provides an exhaustive, step-by-step technical blueprint to replicate, deploy, and operate **NutriCheck AI** on Google Cloud Platform (GCP) and Firebase from scratch.

---

## 1. Accounts & Managed Infrastructure Overview

| Entity / Asset | Details / Identifiers | Purpose |
| :--- | :--- | :--- |
| **User Email** | `smnsreddy08@gmail.com` | Primary administrator account |
| **GitHub Account** | `smnsreddy08-cmd` | Source code repository owner |
| **GitHub Repository** | [`https://github.com/smnsreddy08-cmd/nutricheck-ai`](https://github.com/smnsreddy08-cmd/nutricheck-ai) | Full source code repository |
| **GCP Project ID** | `qwiklabs-gcp-01-60ae6014122e` | Primary Google Cloud Platform project |
| **Firebase Project** | `productinfo-69d4c` | Database project hosting Cloud Firestore |
| **Firebase Console** | [`https://console.firebase.google.com/u/0/project/productinfo-69d4c/firestore`](https://console.firebase.google.com/u/0/project/productinfo-69d4c/firestore) | Real-time database management interface |
| **Agent Engine Resource** | `projects/415074386920/locations/us-east1/reasoningEngines/4487782053093310464` | Vertex AI Reasoning Engine ID |
| **Cloud Run Service** | `https://nutricheck-ai-frontend-415074386920.us-east1.run.app` | Serverless FastAPI UI Proxy & Chat Web Application |
| **GCS Image Storage Bucket** | `gs://nutricheck-ai-assets-qwiklabs-gcp-01-60ae6014122e` | Public bucket for generated nutrition seals and product graphics |

---

## 2. Database Architecture & Firestore Schema

NutriCheck AI uses **Google Cloud Firestore** running in **Datastore Mode / Native Mode** under project `productinfo-69d4c`.

### Collection Name: `products`

Each document inside `products` uses a clean URL slug as its Document ID (e.g. `maggi-2-minute-noodles-masala`, `oreo-chocolate-cream-120g`, `kurkure-masala-munch-85g`, `coca-cola-original-250ml`).

#### Document Field Schema:

```json
{
  "product_id": "maggi-2-minute-noodles-masala",
  "name": "Maggi 2-Minute Noodles Masala Taste",
  "brand": "Maggi",
  "category": "Instant Noodles",
  "pack_size_grams": 70.0,
  "price_inr": 14.0,
  "sugar_grams": 1.26,
  "fat_grams": 8.75,
  "protein_grams": 6.3,
  "sodium_mg": 1750.0,
  "ingredients": "Wheat Flour (Atta), Palm Oil, Salt, Wheat Gluten, Potassium Chloride, Garlic Powder, Onion Powder, Spices and Condiments",
  "chemical_additives": "E150d (Caramel IV), E330 (Citric Acid), E412 (Guar Gum), E451 (Sodium Tripolyphosphate), E500 (Sodium Carbonate), E501 (Potassium Carbonate), E508 (Potassium Chloride)",
  "health_score": 30.0,
  "health_verdict": "Ultra-processed noodle pack with excessive sodium (1750mg) and multiple phosphate stabilizer additives.",
  "updated_at": "2026-09-29T16:00:00Z"
}
```

### Database Connection Mechanism

The agent connects to Firestore using the official `google-cloud-firestore` Python SDK:

```python
from google.cloud import firestore

# Initialized inside app/agent.py via tool definition
db = firestore.Client(project="productinfo-69d4c")
```

**IAM Permissions Required for DB Connection**:
- The GCP Service Account running the agent requires **`roles/datastore.user`** on project `productinfo-69d4c` (or the local project).

---

## 3. External APIs & Cloud Services Accessed

| API / Service | Endpoint / Integration | Description & Role |
| :--- | :--- | :--- |
| **Open Food Facts API** | `https://world.openfoodfacts.org/api/v2/product/{code}.json` | Global product fallback search for unlisted items |
| **Fruityvice Fruit API** | `https://www.fruityvice.com/api/fruit/{name}` | Real-time nutritional facts for whole natural fruits |
| **Google Gemini Flash Lite** | `gemini-3.1-flash-lite-image` | On-demand generation of food concepts & health badges |
| **Google Cloud Storage (GCS)** | `https://storage.googleapis.com/<bucket_name>/` | Uploading and hosting generated image artifacts publicly |
| **Vertex AI Reasoning Engine** | `https://us-east1-aiplatform.googleapis.com/...` | Hosting the serverless ADK agent runtime and A2A API |

---

## 4. Step-by-Step Guide to Replicate NutriCheck AI

### Step 1: Clone the GitHub Repository

```bash
git clone https://github.com/smnsreddy08-cmd/nutricheck-ai.git
cd nutricheck-ai
```

### Step 2: Set Up Python Virtual Environment

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Step 3: Configure GCP & Firebase Authentication

1. Enable required GCP APIs:
   ```bash
   gcloud services enable aiplatform.googleapis.com \
                          firestore.googleapis.com \
                          run.googleapis.com \
                          storage.googleapis.com \
                          cloudbuild.googleapis.com \
                          --project YOUR_GCP_PROJECT_ID
   ```

2. Initialize Firestore Database on Firebase Project `productinfo-69d4c`:
   - Navigate to [Firebase Console](https://console.firebase.google.com/u/0/project/productinfo-69d4c/firestore).
   - Click **Create Database** in Native Mode (`us-east1`).

3. Create Google Cloud Storage Bucket for Image Assets:
   ```bash
   gsutil mb -c standard -l us-east1 gs://nutricheck-ai-assets-YOUR_GCP_PROJECT_ID
   gsutil iam ch allUsers:objectViewer gs://nutricheck-ai-assets-YOUR_GCP_PROJECT_ID
   ```

### Step 4: Deploy the ADK Agent to Vertex AI Reasoning Engine

Use the `agents-cli` deployment workflow:

```bash
agents-cli deploy agentengine \
  --project=YOUR_GCP_PROJECT_ID \
  --region=us-east1 \
  --agent_directory=app \
  --display_name="NutriCheck AI"
```

Save the generated `remote_agent_runtime_id` from `deployment_metadata.json`:
Example: `projects/415074386920/locations/us-east1/reasoningEngines/4487782053093310464`.

### Step 5: Grant Service Account Roles

Grant the deployment Service Account access to Firestore and Storage:

```bash
# Get service account email
SA_EMAIL=$(gcloud reasoning-engines describe 4487782053093310464 --location=us-east1 --format="value(serviceAccount)")

# Grant Firestore access
gcloud projects add-iam-policy-binding productinfo-69d4c \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/datastore.user"

# Grant Storage access
gsutil iam ch serviceAccount:$SA_EMAIL:objectAdmin gs://nutricheck-ai-assets-YOUR_GCP_PROJECT_ID
```

### Step 6: Deploy Frontend Proxy to Cloud Run

Navigate to the `frontend/` directory and deploy to Cloud Run:

```bash
cd frontend

gcloud run deploy nutricheck-ai-frontend \
  --source . \
  --region us-east1 \
  --project YOUR_GCP_PROJECT_ID \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars AGENT_ENGINE_RESOURCE_NAME="projects/415074386920/locations/us-east1/reasoningEngines/4487782053093310464",AGENT_DIRECTORY="app"
```

---

## 5. End-to-End API Verification

Test the live endpoint with `curl`:

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"message": "Check Maggi 2-Minute Noodles for sodium and INS chemical additives."}' \
  https://nutricheck-ai-frontend-415074386920.us-east1.run.app/chat
```

### Expected Output:
- Rich **A2UI surface JSON payload** containing:
  - Product Reality & Nutritional Summary
  - Chemical Additives Breakdown (`E150d`, `E330`, `E412`, `E451`, `E500`, `E501`, `E508`)
  - Overall Health Score (`30/100`)
  - Public Cloud Storage URL for the visual **Health Warning Seal graphic**.

---

## Summary Checklist

- [x] Code hosted on GitHub: `https://github.com/smnsreddy08-cmd/nutricheck-ai`
- [x] Firebase Firestore DB configured: `productinfo-69d4c`
- [x] Agent Engine active on Vertex AI Reasoning Engine
- [x] Cloud Run Frontend deployed & publicly accessible
- [x] A2UI surface rendering enabled with 10 custom nutrition tools
