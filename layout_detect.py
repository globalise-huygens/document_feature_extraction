# Uses OpenAI Python SDK v1.x style
import os
import json
import base64
import mimetypes
import time
import openai

# === HARD‑CODED CONFIG ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")
IMAGES_DIR = "/Users/gavinl/Desktop/Test Set for LLM Layout Extraction/Images"
REGION_TYPES_DIR = "/Users/gavinl/Desktop/Test Set for LLM Layout Extraction/JSON"
OUTPUT_DIR = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Feature Sets/7924_features - (o4-mini)"
# =========================

# Create an OpenAI client instance (v1.x style)
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def image_to_data_uri(image_path: str) -> str:
    """
    Read an image file and return a data URI (base64-encoded string with MIME type).
    This is used to send the image in the OpenAI chat message.
    """
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith('image'):
        raise ValueError(f"The file {image_path} is not recognized as an image.")
    with open(image_path, "rb") as img_file:
        encoded = base64.b64encode(img_file.read()).decode('utf-8')
    data_uri = f"data:{mime_type};base64,{encoded}"
    return data_uri

def call_gpt4_vision(image_path: str, region_types: list, max_retries: int = 3) -> str:
    """
    Call the GPT-4 Vision API to analyze the image and return the JSON string output.
    Retries on rate limit or server errors up to max_retries.
    """
    # Prepare the prompt instruction for this image
    region_list_str = ", ".join(region_types)
    prompt_text = (
        "You are a document layout analysis assistant. "
        "Identify all regions in the image that correspond to the following types: "
        f"{region_list_str}. "  # list of types
        "For each detected region, output its type and precise polygon coordinates outlining the region. "
        "Polygons should be tight around content and have a tolerance of at most 2 pixels. "
        "No region should overlap or share any pixel with another. "
        "Output the result as a JSON object with a 'regions' field containing a list of region objects. "
        "Each region object should have 'type' and 'polygon' keys. "
        "The polygon should be an array of [x, y] coordinates of the vertices. "
        "Do NOT include any extra text, only the JSON object."
    )
    # ---- System prompt giving deep context about VOC manuscripts ----
    system_prompt = (
        "You are an expert historical‑document layout analyst specialising in 17th‑ and 18th‑century Dutch East India Company "
        "(VOC) archives. These pages are handwritten, often on rag paper, and exhibit:\n"
        "• Long, narrow ‘paragraph’ blocks justified on the left margin, sometimes separated by a single ruled line.\n"
        "• Marginalia in the outer gutter noting ship names, dates or folio references; these can be vertical or slanted.\n"
        "• ‘Catch‑words’ at the bottom‑right of a page—usually the first word of the next page—written in smaller cursive.\n"
        "• Roman‑numeral page numbers centred at the very top margin in a darker ink.\n"
        "• Signature‑marks (e.g. ‘A‑ii’) at the bottom‑centre, used by the binder; these are smaller than body text and often "
        "offset a few millimetres below the last baseline.\n\n"
        "Nuances to observe:\n"
        "1. Ink bleed‑through means a faint mirrored impression of the verso text may appear; ignore this when segmenting.\n"
        "2. Paper wrinkling causes baseline curvature—polygon vertices must follow the visual contour rather than assume a flat box.\n"
        "3. Some marginalia overlap the ruled border; include only the written strokes, not the border, in the polygon.\n"
        "4. Where a catch‑word collides with a signature‑mark, prioritise the catch‑word region and shrink the signature polygon to avoid overlap.\n"
        "5. All coordinates are absolute pixel positions in the **original** image (≈300 dpi); do not normalise or scale.\n\n"
        "Output strictly the JSON object described below—no commentary. If confidence for a region is <90 %, append a "
        "“_confidence” key (0‑1 float).\n"
    )
    # Encode image to data URI
    data_uri = image_to_data_uri(image_path)
    # Build the messages payload for the OpenAI API
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}}
        ]}
    ]
    # Try calling the API with retries
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="o4-mini-2025-04-16",  # vision‑enabled flagship model
                messages=messages,
                temperature=1.0,  # deterministic output
            )
            # Extract the assistant's message content (should be JSON string)
            content = response.choices[0].message.content
            return content  # return raw JSON string (to be parsed by caller)
        except openai.RateLimitError as e:
            # Handle rate limiting: wait and retry with exponential backoff
            wait_time = 2 ** attempt  # e.g., 1, 2, 4 seconds for attempts 0,1,2...
            print(f"Rate limit encountered. Waiting {wait_time} seconds before retry... (Attempt {attempt+1}/{max_retries})")
            time.sleep(wait_time)
            # then loop to retry
        except openai.APIError as e:
            # Handle other API errors (e.g. 500 server error)
            status = getattr(e, "status_code", "unknown")
            print(f"OpenAI API returned an error (status {status}): {e}.")
            # If it's a server error or temporary issue, we might retry after a short wait
            if attempt < max_retries - 1:
                time.sleep(1)
                continue  # retry
            else:
                raise  # give up after max retries
        except openai.NotFoundError as e:
            # Model or resource not found – likely wrong model name or unavailable in account
            print(f"NotFoundError: {e}. Check that the model name is correct and that your account has access.")
            raise  # propagate so outer caller can decide to retry/skip
        except openai.APIConnectionError as e:
            # Handle network errors
            print(f"Connection error when calling OpenAI API: {e}.")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            else:
                raise
        except openai.AuthenticationError as e:
            # Invalid API key or unauthorized
            raise RuntimeError(f"Authentication failed: {e}") from e
        except Exception as e:
            # Catch-all for any other exceptions
            raise RuntimeError(f"Failed to get GPT-4 Vision response for {image_path}: {e}") from e
    # If we exited loop without returning, it means retries failed
    raise RuntimeError(f"Max retries exceeded for {image_path} due to repeated errors.")

def main(images_dir: str, region_types_dir: str, output_dir: str):
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    # Load region types JSON (assuming one main JSON file in the region_types_dir)
    region_types_files = [f for f in os.listdir(region_types_dir) if f.lower().endswith(".json")]
    if not region_types_files:
        raise FileNotFoundError(f"No JSON files found in region types directory: {region_types_dir}")
    region_types_path = os.path.join(region_types_dir, region_types_files[0])
    with open(region_types_path, "r", encoding="utf-8") as f:
        region_mapping = json.load(f)
    # Accept both dict {type: color} and list [{"type": ..., "color": ...}, ...]
    if isinstance(region_mapping, list):
        # Convert list of objects (possibly missing a color) into {type_name: color_or_None}
        new_mapping = {}
        for item in region_mapping:
            if not isinstance(item, dict):
                continue  # skip malformed
            # Determine the key (prefer "type", fallback to "name")
            if "type" in item:
                key = item["type"]
            elif "name" in item:
                key = item["name"]
            else:
                continue  # cannot identify region name
            # Accept any of several possible color keys; None if absent
            color_val = item.get("color") or item.get("colour") or item.get("hex") or item.get("value")
            new_mapping[key] = color_val
        region_mapping = new_mapping
    elif not isinstance(region_mapping, dict):
        raise ValueError(
            "Region‑types JSON file must be either a dict {type: color} "
            "or a list of objects containing at least a 'type' or 'name' field."
        )
    # region_mapping is a dict of {region_name: color}. Get list of region names:
    region_types_list = list(region_mapping.keys())
    print(f"Loaded region types: {region_types_list}")
    # Process each image in the images_dir
    images = [f for f in os.listdir(images_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    if not images:
        raise FileNotFoundError(f"No images found in directory: {images_dir}")
    for image_file in images:
        image_path = os.path.join(images_dir, image_file)
        output_path = os.path.join(output_dir, os.path.splitext(image_file)[0] + ".json")
        try:
            print(f"Processing image: {image_file}...")
            # Call GPT-4 Vision API to get JSON result as string
            json_content = call_gpt4_vision(image_path, region_types_list)
        except Exception as e:
            # If there's an error (e.g., API failure), log and continue to next image
            print(f"Error processing {image_file}: {e}")
            continue
        # Try to parse the returned JSON content
        parsed = None
        try:
            parsed = json.loads(json_content.strip())
        except json.JSONDecodeError as e:
            # If initial parse fails, try to clean common formatting issues
            cleaned = json_content
            # Remove any code block markdown or text outside JSON if present
            if cleaned.strip().startswith("```"):
                cleaned = cleaned.strip().strip("`")  # remove surrounding backticks
            # Sometimes the assistant might include a leading explanation – find first brace
            brace_index = cleaned.find("{")
            if brace_index != -1:
                cleaned = cleaned[brace_index:]
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                print(f"Failed to parse JSON output for {image_file}. The raw output will be saved for review.")
                # Save the raw output to file for debugging, then skip
                with open(output_path, "w", encoding="utf-8") as out_f:
                    out_f.write(json_content)
                continue
        # If parsed successfully, validate the content structure
        if parsed is None or "regions" not in parsed or not isinstance(parsed["regions"], list):
            print(f"Unexpected JSON structure for {image_file}. Saving raw output for review.")
            with open(output_path, "w", encoding="utf-8") as out_f:
                out_f.write(json_content)
            continue
        # Validate each region's type
        valid_regions = []
        for region in parsed["regions"]:
            if "type" not in region or "polygon" not in region:
                continue  # skip malformed region entry
            rtype = region["type"]
            if rtype not in region_mapping:
                print(f"Warning: Unrecognized region type '{rtype}' in {image_file}. Skipping this region.")
                continue
            # We might also validate polygon coordinates format here (e.g., list of lists of two numbers)
            valid_regions.append({"type": rtype, "polygon": region["polygon"]})
        # Write the validated regions to the output JSON
        output_data = {"regions": valid_regions}
        with open(output_path, "w", encoding="utf-8") as out_f:
            json.dump(output_data, out_f, ensure_ascii=False, indent=4)
        print(f"Saved output to {output_path}")

if __name__ == "__main__":
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_api_key_here":
        raise RuntimeError("OPENAI_API_KEY not set. Edit OPENAI_API_KEY in this file or export it in the environment.")
    main(IMAGES_DIR, REGION_TYPES_DIR, OUTPUT_DIR)