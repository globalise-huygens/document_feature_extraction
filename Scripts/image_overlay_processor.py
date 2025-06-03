import os
import xml.etree.ElementTree as ET
import json
from PIL import Image, ImageDraw
import re

# --- Configuration: Define SEMI-TRANSPARENT colors for different region types ---
# Colors are in (R, G, B, A) format, where A is the alpha/transparency (0-255)
# An alpha value of 100 gives a nice semi-transparent fill.
REGION_COLORS_FILL = {
    "paragraph":      (0, 0, 255, 100),       # Blue
    "marginalia":     (0, 128, 0, 100),       # Green
    "signature-mark": (255, 0, 0, 100),       # Red
    "header":         (128, 0, 128, 100),     # Purple
    "catch-word":     (255, 165, 0, 100),   # Orange
    "page-number":    (255, 255, 0, 100),  # Yellow
    "default":        (128, 128, 128, 100)    # Grey for unknown types
}

def parse_page_xml_regions(xml_file_path):
    """
    Parses a PAGE XML file to extract region types and polygon coordinates.
    """
    regions = []
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
        ns = {'page': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15'}

        page_element = root.find('page:Page', ns)
        if page_element is None:
            print(f"Warning: No Page element found in {xml_file_path}")
            return []

        for text_region in page_element.findall('page:TextRegion', ns):
            region_type = "unknown"
            custom_attr = text_region.get('custom', '')
            match = re.search(r'type:\s*([^;}]+)', custom_attr)
            if match:
                region_type = match.group(1).strip()

            coords_element = text_region.find('page:Coords', ns)
            if coords_element is not None:
                points_str = coords_element.get('points')
                if points_str:
                    polygon_coords = []
                    try:
                        for point_pair in points_str.split():
                            x_str, y_str = point_pair.split(',')
                            polygon_coords.append((int(x_str), int(y_str)))
                        if polygon_coords:
                             regions.append({'type': region_type, 'polygon': polygon_coords})
                    except ValueError:
                        print(f"Warning: Could not parse coordinates '{points_str}' in {xml_file_path} for region ID {text_region.get('id')}")
                        continue
    except ET.ParseError:
        print(f"Error: Could not parse XML file {xml_file_path}")
    except Exception as e:
        print(f"An unexpected error occurred while parsing XML {xml_file_path}: {e}")
    return regions

def parse_json_regions(json_file_path):
    """
    Parses a JSON file to extract region types and polygon coordinates.
    """
    regions = []
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'regions' in data and isinstance(data['regions'], list):
            for region_data in data['regions']:
                if 'type' in region_data and 'polygon' in region_data:
                    polygon_tuples = [tuple(p) for p in region_data['polygon']]
                    regions.append({'type': region_data['type'], 'polygon': polygon_tuples})
                else:
                    print(f"Warning: Skipping region with missing 'type' or 'polygon' in {json_file_path}")
        else:
            print(f"Warning: JSON file {json_file_path} does not contain a 'regions' list.")
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from file {json_file_path}")
    except Exception as e:
        print(f"An unexpected error occurred while parsing JSON {json_file_path}: {e}")
    return regions

def draw_filled_regions_on_image(base_image, regions_data, colors):
    """
    Draws semi-transparent filled polygons on a copy of the image.
    This works by creating a transparent overlay, drawing on it, and then
    compositing it onto the original image.
    """
    # The base image must be in RGBA mode for alpha compositing
    base_image_rgba = base_image.convert('RGBA')
    
    # Create a transparent overlay layer
    overlay = Image.new('RGBA', base_image_rgba.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    for region in regions_data:
        region_type = region['type']
        polygon = region['polygon']
        # Get the RGBA color for the region type
        color = colors.get(region_type, colors.get("default"))
        
        if polygon and len(polygon) > 2: # Need at least 3 points for a filled polygon
            draw.polygon(polygon, fill=color)

    # Alpha composite the overlay onto the base image
    combined_image = Image.alpha_composite(base_image_rgba, overlay)
    
    return combined_image

def process_directories(image_dir, xml_dir, json_dir, output_dir):
    """
    Processes all images, applies overlays, and saves the combined output.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    processed_files = 0
    for image_filename in os.listdir(image_dir):
        if image_filename.startswith("._"):
            print(f"  Skipping hidden macOS file: {image_filename}")
            continue

        if not (image_filename.lower().endswith(".jpg") or image_filename.lower().endswith(".jpeg")):
            continue

        base_name, _ = os.path.splitext(image_filename)
        image_path = os.path.join(image_dir, image_filename)
        xml_path = os.path.join(xml_dir, base_name + ".xml")
        json_path = os.path.join(json_dir, base_name + ".json")

        print(f"\nProcessing image: {image_filename}")

        xml_regions = parse_page_xml_regions(xml_path) if os.path.exists(xml_path) else []
        if not os.path.exists(xml_path):
            print(f"  Warning: XML file not found at {xml_path}. Skipping XML overlay.")

        json_regions = parse_json_regions(json_path) if os.path.exists(json_path) else []
        if not os.path.exists(json_path):
            print(f"  Warning: JSON file not found at {json_path}. Skipping JSON overlay.")

        try:
            original_image = Image.open(image_path)
        except Exception as e:
            print(f"  Error opening image {image_path}: {e}. Skipping.")
            continue

        # Create two copies for left and right side processing
        img_left = original_image.copy()
        img_right = original_image.copy()

        # Draw filled XML regions on the left image
        if xml_regions:
            img_left = draw_filled_regions_on_image(img_left, xml_regions, REGION_COLORS_FILL)
            print(f"  Applied {len(xml_regions)} filled XML overlays to left image.")
        
        # Draw filled JSON regions on the right image
        if json_regions:
            img_right = draw_filled_regions_on_image(img_right, json_regions, REGION_COLORS_FILL)
            print(f"  Applied {len(json_regions)} filled JSON overlays to right image.")

        # Combine images side-by-side
        total_width = original_image.width * 2
        height = original_image.height
        
        # Convert images back to RGB if they are RGBA, as JPEG does not support transparency
        img_left = img_left.convert('RGB')
        img_right = img_right.convert('RGB')
        
        combined_image = Image.new('RGB', (total_width, height))
        combined_image.paste(img_left, (0, 0))
        combined_image.paste(img_right, (original_image.width, 0))

        # Save the combined image
        output_filename = base_name + "_filled_overlay.jpg"
        output_path = os.path.join(output_dir, output_filename)
        try:
            combined_image.save(output_path, "JPEG")
            print(f"  Successfully saved combined image to: {output_path}")
            processed_files += 1
        except Exception as e:
            print(f"  Error saving image {output_path}: {e}")
            
    if processed_files == 0:
        print("\nNo image files were processed. Please check your input directories and file names.")
    else:
        print(f"\nFinished processing. {processed_files} images were generated.")

if __name__ == '__main__':
    # --- IMPORTANT: User Configuration ---
    # Please replace these placeholder paths with the actual paths to your directories.
    
    current_script_path = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()

    IMAGE_INPUT_DIR = "/Users/gavinl/Desktop/Test Set for LLM Layout Extraction/Images"
    XML_INPUT_DIR = "/Users/gavinl/Desktop/Test Set for LLM Layout Extraction/XML"
    JSON_INPUT_DIR = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Feature Sets/7924_features - (o4-mini)"
    OUTPUT_DIR = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Feature Sets/7924_image_comparison - (o4-mini)"

    for d in [IMAGE_INPUT_DIR, XML_INPUT_DIR, JSON_INPUT_DIR]:
        os.makedirs(d, exist_ok=True)
    
    print(f"Expecting images in: {IMAGE_INPUT_DIR}")
    print(f"Expecting XML files in: {XML_INPUT_DIR}")
    print(f"Expecting JSON files in: {JSON_INPUT_DIR}")
    print(f"Output will be saved to: {OUTPUT_DIR}")
    print("-" * 30)
    
    process_directories(IMAGE_INPUT_DIR, XML_INPUT_DIR, JSON_INPUT_DIR, OUTPUT_DIR)