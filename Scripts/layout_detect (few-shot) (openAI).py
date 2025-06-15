#!/usr/bin/env python3
"""
layout_detect.py

Few-shot GPT-4o Vision layout-segmentation script for VOC manuscripts.

Directory layout (hard-coded for simplicity):
├── EXAMPLES_SCANS_DIR/          # *.jpg / *.jpeg
├── EXAMPLES_REGION_DIR/         # *.json (region types + text)
├── EXAMPLES_COORD_DIR/          # *.json (ground-truth coordinate output)
├── IMAGES_DIR/                  # target scans
├── REGION_JSON_DIR/             # target region JSONs (with text)
└── OUTPUT_DIR/                  # coordinate-only JSONs written here

All files share the same basename (before extension).
"""

import os
import json
import base64
import mimetypes
import time
from typing import List, Dict

import openai


# ---------- HARD-CODED CONFIG -------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "api key here")

# Directories
EXAMPLES_SCANS_DIR   = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Examples/Page Scans"
EXAMPLES_REGION_DIR  = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Examples/Region JSON"
EXAMPLES_COORD_DIR   = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Examples/Coordinate JSON"

IMAGES_DIR           = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Few-shot_test/images"
REGION_JSON_DIR      = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Few-shot_test/Region JSON"
OUTPUT_DIR           = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Few-shot_test/output"

NUM_EXAMPLES         = 1      # how many aligned examples to include in the prompt
MODEL_NAME           = "o4-mini-2025-04-16"   # vision-capable model
MAX_RETRIES          = 3
# -----------------------------------------------------------------------------

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# ---------- UTILITIES ---------------------------------------------------------
def image_to_data_uri(image_path: str) -> str:
    """Convert a local image (jpg / png) to a data URI string."""
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith("image"):
        raise ValueError(f"{image_path} is not recognised as an image.")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


def load_json(path: str) -> str:
    """Return the raw JSON string from a file, stripped of whitespace."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def collect_example_basenames(n: int) -> List[str]:
    """Return up to n basenames present in all three example dirs."""
    region_files = {os.path.splitext(f)[0] for f in os.listdir(EXAMPLES_REGION_DIR)
                    if f.lower().endswith(".json")}
    coord_files  = {os.path.splitext(f)[0] for f in os.listdir(EXAMPLES_COORD_DIR)
                    if f.lower().endswith(".json")}
    scan_files   = {os.path.splitext(f)[0] for f in os.listdir(EXAMPLES_SCANS_DIR)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))}
    common = sorted(region_files & coord_files & scan_files)
    return common[:n]


def build_fewshot_messages(example_basenames: List[str]) -> List[Dict]:
    """Create a list of (system, user, assistant) messages for few-shot."""
    messages: List[Dict] = []

    # System prompt – VOC nuance (same as earlier, but centralised)
    system_prompt = (
        "You are an expert historical-document layout analyst specialising in 17th- and "
        "18th-century Dutch East India Company (VOC) archives. "
        "Pages contain: paragraphs, marginalia, catch-words, page numbers, signature-marks. "
        "Ink bleed-through, wrinkled baselines, etc. Output must be precise polygons, "
        "disjoint, ≤2 px tolerance. Respond ONLY with the coordinate JSON described below."
    )
    messages.append({"role": "system", "content": system_prompt})

    # Build each example as a user→assistant exchange
    for base in example_basenames:
        img_path   = os.path.join(EXAMPLES_SCANS_DIR,   f"{base}.jpg")
        if not os.path.exists(img_path):  # fallback to .jpeg/.png
            for ext in (".jpeg", ".png"):
                alt = os.path.join(EXAMPLES_SCANS_DIR, f"{base}{ext}")
                if os.path.exists(alt):
                    img_path = alt
                    break

        region_json_str = load_json(os.path.join(EXAMPLES_REGION_DIR, f"{base}.json"))
        coord_json_str  = load_json(os.path.join(EXAMPLES_COORD_DIR,  f"{base}.json"))

        user_content = [
            {"type": "text", "text": (
                "Example input:\n"
                f"Region JSON (with transcribed text):\n{region_json_str}\n\n"
                "Provide the coordinate-only JSON for this page."
            )},
            {"type": "image_url", "image_url": {"url": image_to_data_uri(img_path),
                                                "detail": "high"}}
        ]
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": coord_json_str})

    return messages
# -----------------------------------------------------------------------------


def call_gpt4_vision(messages: List[Dict], max_retries: int = MAX_RETRIES) -> str:
    """Send chat completion with given message array; return assistant content."""
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=1.0
            )
            return resp.choices[0].message.content.strip()
        except openai.RateLimitError:
            wait = 2 ** attempt
            print(f"Rate-limit; retrying in {wait}s…")
            time.sleep(wait)
        except openai.APIError as e:
            status = getattr(e, "status_code", "unknown")
            print(f"API error (status {status}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
        except openai.NotFoundError as e:
            raise RuntimeError(
                f"Model {MODEL_NAME} not available to this key: {e}"
            ) from e
    raise RuntimeError("Exceeded maximum retries.")


def main() -> None:
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_api_key_here":
        raise RuntimeError("Set your OPENAI_API_KEY in env or in the constant.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ----- Few-shot examples --------------------------------------------------
    example_basenames = collect_example_basenames(NUM_EXAMPLES)
    if len(example_basenames) < NUM_EXAMPLES:
        print("⚠️  Warning: fewer examples found than requested.")
    base_messages = build_fewshot_messages(example_basenames)
    # -------------------------------------------------------------------------

    # ----- Iterate over target pages ----------------------------------------
    for fname in sorted(os.listdir(IMAGES_DIR)):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        basename, _ = os.path.splitext(fname)
        region_path = os.path.join(REGION_JSON_DIR, f"{basename}.json")
        if not os.path.exists(region_path):
            print(f"⚠️  Region JSON missing for {basename}; skipping.")
            continue

        out_path = os.path.join(OUTPUT_DIR, f"{basename}.json")
        print(f"Processing {basename}…")

        # Build new user query appended to few-shot context
        region_json_str = load_json(region_path)
        img_path = os.path.join(IMAGES_DIR, fname)
        user_query = {
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Input:\n"
                    f"Region JSON (with transcribed text):\n{region_json_str}\n\n"
                    "Output only the coordinate JSON for this page."
                )},
                {"type": "image_url", "image_url": {"url": image_to_data_uri(img_path),
                                                    "detail": "high"}}
            ]
        }

        messages = base_messages + [user_query]

        try:
            coord_json_str = call_gpt4_vision(messages)
        except Exception as e:
            print(f"❌ Error on {basename}: {e}")
            continue

        # Validate / clean JSON
        try:
            parsed = json.loads(coord_json_str)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            print(f"✅ Saved {out_path}")
        except json.JSONDecodeError:
            # save raw for debugging
            print(f"⚠️  Non-JSON output for {basename}; saving raw.")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(coord_json_str)


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()