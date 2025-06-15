#!/usr/bin/env python3
"""
layout_detect.py

Few-shot Gemini 1.5 Pro Vision layout-segmentation script for VOC manuscripts.

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
from typing import List, Dict, Union, Any

import google.generativeai as genai
from google.api_core import exceptions


# ---------- HARD-CODED CONFIG -------------------------------------------------
# Ensure you have your Gemini API key set as an environment variable
GEMINI_API_KEY = "api key here"

# Directories
EXAMPLES_SCANS_DIR   = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Examples/Page Scans"
EXAMPLES_REGION_DIR  = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Examples/Region JSON"
EXAMPLES_COORD_DIR   = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Examples/Coordinate JSON"

IMAGES_DIR           = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Few-shot_test (Gemini)/images"
REGION_JSON_DIR      = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Few-shot_test (Gemini)/Region JSON"
OUTPUT_DIR           = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Few-shot_test (Gemini)/output"

NUM_EXAMPLES         = 1      # how many aligned examples to include in the prompt
MODEL_NAME           = "gemini-2.5-pro-preview-06-05"   # vision-capable model
MAX_RETRIES          = 3
# -----------------------------------------------------------------------------

genai.configure(api_key=GEMINI_API_KEY)


# ---------- UTILITIES ---------------------------------------------------------
def image_to_data_uri(image_path: str) -> Dict[str, str]:
    """Convert a local image (jpg / png) to a dictionary for Gemini API."""
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith("image"):
        raise ValueError(f"{image_path} is not recognised as an image.")
    with open(image_path, "rb") as f:
        data = f.read()
    return {"mime_type": mime_type, "data": data}


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


def build_fewshot_messages() -> List[Dict[str, Any]]:
    """Create a list of messages for few-shot prompting with Gemini."""
    system_prompt = (
        "You are an expert historical-document layout analyst specialising in 17th- and "
        "18th-century Dutch East India Company (VOC) archives. "
        "Pages contain: paragraphs, marginalia, catch-words, page numbers, signature-marks. "
        "Ink bleed-through, wrinkled baselines, etc. Output must be precise polygons, "
        "disjoint, ≤2 px tolerance. Respond ONLY with the coordinate JSON described below."
    )
    
    example_basenames = collect_example_basenames(NUM_EXAMPLES)
    if len(example_basenames) < NUM_EXAMPLES:
        print("⚠️  Warning: fewer examples found than requested.")

    # The history will contain the examples for the few-shot prompt
    history = []
    
    # Build each example as a user->model exchange
    for base in example_basenames:
        img_path = os.path.join(EXAMPLES_SCANS_DIR, f"{base}.jpg")
        if not os.path.exists(img_path):
            for ext in (".jpeg", ".png"):
                alt = os.path.join(EXAMPLES_SCANS_DIR, f"{base}{ext}")
                if os.path.exists(alt):
                    img_path = alt
                    break

        region_json_str = load_json(os.path.join(EXAMPLES_REGION_DIR, f"{base}.json"))
        coord_json_str = load_json(os.path.join(EXAMPLES_COORD_DIR, f"{base}.json"))
        
        user_prompt = [
            "Example input:",
            f"Region JSON (with transcribed text):\n{region_json_str}\n\n",
            "Provide the coordinate-only JSON for this page.",
            image_to_data_uri(img_path)
        ]

        history.append({'role': 'user', 'parts': user_prompt})
        history.append({'role': 'model', 'parts': [coord_json_str]})

    return system_prompt, history
# -----------------------------------------------------------------------------


def call_gemini_vision(system_prompt: str, history: List[Dict], user_query: List[Union[str, Dict]], max_retries: int = MAX_RETRIES) -> str:
    """Send a request to the Gemini API with a few-shot history."""
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=system_prompt)
    
    chat = model.start_chat(history=history)

    for attempt in range(max_retries):
        try:
            response = chat.send_message(user_query)
            return response.text.strip()
        except exceptions.ResourceExhausted as e:
            wait = 2 ** attempt
            print(f"Rate-limit or resource exhausted; retrying in {wait}s…")
            time.sleep(wait)
        except exceptions.GoogleAPICallError as e:
            print(f"API call error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    raise RuntimeError("Exceeded maximum retries.")


def main() -> None:
    if not GEMINI_API_KEY:
        raise RuntimeError("Set your GEMINI_API_KEY in env.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ----- Few-shot examples --------------------------------------------------
    system_prompt, history = build_fewshot_messages()
    # -------------------------------------------------------------------------

    # ----- Iterate over target pages ----------------------------------------
    for fname in sorted(os.listdir(IMAGES_DIR)):
        if fname.startswith('._'): # <--- ADD THIS LINE TO IGNORE MACOS FILES
            continue
            
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        basename, _ = os.path.splitext(fname)
        region_path = os.path.join(REGION_JSON_DIR, f"{basename}.json")
        if not os.path.exists(region_path):
            print(f"⚠️  Region JSON missing for {basename}; skipping.")
            continue

        out_path = os.path.join(OUTPUT_DIR, f"{basename}.json")
        print(f"Processing {basename}…")

        # Build new user query
        region_json_str = load_json(region_path)
        img_path = os.path.join(IMAGES_DIR, fname)
        
        user_query = [
            "Input:",
            f"Region JSON (with transcribed text):\n{region_json_str}\n\n",
            "Output only the coordinate JSON for this page.",
            image_to_data_uri(img_path)
        ]

        try:
            coord_json_str = call_gemini_vision(system_prompt, history, user_query)
        except Exception as e:
            print(f"❌ Error on {basename}: {e}")
            continue

        # Validate / clean JSON
        try:
            # The Gemini API might wrap the JSON in markdown
            if coord_json_str.startswith("```json"):
                coord_json_str = coord_json_str[7:-4].strip()
            
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