import os
import xml.etree.ElementTree as ET
import json
from PIL import Image, ImageDraw, ImageFont # Ensure ImageFont is imported
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

# --- Configuration for Text Labels ---
TEXT_COLOR = (0, 0, 0, 255)  # Black, fully opaque for good visibility
TEXT_SIZE = 100               # Desired text size for labels (adjust as needed)
# Try to load a common system font.
# If "arial.ttf" or "DejaVuSans.ttf" is not found in default paths,
# provide the full path to a .ttf or .otf font file you have.
PRIMARY_FONT_PATH = "arial.ttf"
FALLBACK_FONT_PATH = "DejaVuSans.ttf" # A common font on Linux systems

FONT = None
try:
    FONT = ImageFont.truetype(PRIMARY_FONT_PATH, TEXT_SIZE)
    print(f"Successfully loaded font: {PRIMARY_FONT_PATH} with size {TEXT_SIZE}")
except IOError:
    print(f"Warning: Font '{PRIMARY_FONT_PATH}' not found. Trying fallback font '{FALLBACK_FONT_PATH}'.")
    try:
        FONT = ImageFont.truetype(FALLBACK_FONT_PATH, TEXT_SIZE)
        print(f"Successfully loaded font: {FALLBACK_FONT_PATH} with size {TEXT_SIZE}")
    except IOError:
        print(f"Warning: Fallback font '{FALLBACK_FONT_PATH}' also not found.")
        try:
            # Check Pillow version for modern default font sizing
            from PIL import __version__ as PIL_VERSION
            pil_version_tuple = tuple(map(int, PIL_VERSION.split('.')))
            if pil_version_tuple >= (9, 2, 0):
                FONT = ImageFont.load_default(size=TEXT_SIZE)
                print(f"Using default PIL font with requested size {TEXT_SIZE} (Pillow version {PIL_VERSION}).")
            else:
                FONT = ImageFont.load_default() # Older Pillow, default size only
                print(f"Using default PIL font with its standard small size (Pillow version {PIL_VERSION} < 9.2.0). Text might be small. Consider providing a valid .ttf font path for better control.")
        except Exception as e_default_font:
            print(f"Error loading default font: {e_default_font}. Text drawing will be skipped.")
            FONT = None # Critical failure to load any font
except Exception as e_general_font:
    print(f"An unexpected error occurred during font loading: {e_general_font}. Text drawing might be skipped.")
    FONT = None


def parse_page_xml_regions(xml_file_path):
    """
    Parses a PAGE XML file to extract region types and polygon coordinates.
    """
    regions = []
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
        # Dynamically get the namespace
        ns_match = re.match(r'\{([^}]+)\}', root.tag)
        ns_uri = ns_match.group(1) if ns_match else 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15' # Default if not found
        ns = {'page': ns_uri}


        page_element = root.find('page:Page', ns)
        if page_element is None:
            print(f"Warning: No Page element found in {xml_file_path} using namespace {ns_uri}")
            # Try without namespace if the first attempt fails (though PAGE XML usually has one)
            page_element = root.find('Page')
            if page_element is None:
                print(f"Warning: No Page element found in {xml_file_path} even without namespace. Skipping.")
                return []
            else: # No namespace was used for Page, so clear ns for subsequent finds
                ns = {}


        # Iterate over various region types that might contain Coords
        region_tags = ['TextRegion', 'ImageRegion', 'LineDrawingRegion', 'GraphicRegion', 'TableRegion', 'ChartRegion', 'SeparatorRegion', 'MathsRegion', 'ChemRegion', 'MusicRegion', 'AdvertRegion', 'NoiseRegion', 'UnknownRegion', 'CustomRegion']
        
        for region_tag in region_tags:
            find_query = f'page:{region_tag}' if ns else region_tag
            for element_region in page_element.findall(find_query, ns):
                region_type = "unknown" # Default
                custom_attr = element_region.get('custom', '')
                
                # Try to get type from 'custom' attribute first
                match = re.search(r'type:\s*([^;}]+)', custom_attr)
                if match:
                    region_type = match.group(1).strip()
                else: # Fallback to using the tag name itself as type (excluding namespace part)
                    region_type = element_region.tag.split('}')[-1] if '}' in element_region.tag else element_region.tag


                coords_element_query = 'page:Coords' if ns else 'Coords'
                coords_element = element_region.find(coords_element_query, ns)
                
                if coords_element is not None:
                    points_str = coords_element.get('points')
                    if points_str:
                        polygon_coords = []
                        try:
                            for point_pair in points_str.split():
                                x_str, y_str = point_pair.split(',')
                                polygon_coords.append((int(float(x_str)), int(float(y_str)))) # Using float for conversion robustness
                            if polygon_coords:
                                 regions.append({'type': region_type, 'polygon': polygon_coords})
                        except ValueError:
                            print(f"Warning: Could not parse coordinates '{points_str}' in {xml_file_path} for region ID {element_region.get('id')}")
                            continue
    except ET.ParseError:
        print(f"Error: Could not parse XML file {xml_file_path}")
    except Exception as e:
        print(f"An unexpected error occurred while parsing XML {xml_file_path}: {e}")
    return regions

def parse_json_regions_simplified(json_file_path):
    """
    Parses a JSON file (list of dicts format) to extract region types 
    and 'simplified_polygon' coordinates.
    """
    regions = []
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list): # New format: JSON is a list of region dictionaries
            for region_data in data:
                if 'type' in region_data and 'simplified_polygon' in region_data:
                    # Ensure polygon coordinates are tuples, as Pillow's ImageDraw expects
                    polygon_tuples = [tuple(p) for p in region_data['simplified_polygon']]
                    regions.append({'type': region_data['type'], 'polygon': polygon_tuples})
                else:
                    print(f"Warning: Skipping region with missing 'type' or 'simplified_polygon' in {json_file_path}")
        else:
            print(f"Warning: JSON file {json_file_path} is not in the expected list format.")
            
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from file {json_file_path}")
    except Exception as e:
        print(f"An unexpected error occurred while parsing JSON {json_file_path}: {e}")
    return regions

def draw_filled_regions_on_image(base_image, regions_data, colors_map):
    """
    Draws semi-transparent filled polygons and their labels on a copy of the image.
    The labels will be the keys from the 'colors_map' (REGION_COLORS_FILL).
    """
    if not regions_data: # No regions to draw
        return base_image.convert('RGBA') # Return a modifiable RGBA copy

    base_image_rgba = base_image.convert('RGBA')
    overlay = Image.new('RGBA', base_image_rgba.size, (255, 255, 255, 0)) # Transparent overlay
    draw = ImageDraw.Draw(overlay) # Draw polygons and text on this overlay

    font_warning_printed_this_call = False 

    for region in regions_data:
        region_type_from_data = region.get('type', 'default') 
        polygon = region.get('polygon')
        
        actual_color_key_used = "default" # Start with default
        color_to_use = colors_map.get("default") # Get default color initially

        if region_type_from_data in colors_map:
            actual_color_key_used = region_type_from_data
            color_to_use = colors_map[actual_color_key_used]
        
        if polygon and len(polygon) > 2: # Need at least 3 points for a filled polygon
            try:
                if color_to_use: # Ensure we have a color before drawing
                    draw.polygon(polygon, fill=color_to_use)
                else:
                    print(f"  Warning: No color found for region type '{region_type_from_data}' or default. Skipping fill.")

                # --- Add text label ---
                if FONT: 
                    try:
                        min_x = min(p[0] for p in polygon)
                        min_y = min(p[1] for p in polygon)
                        
                        text_x = min_x + 5 
                        text_y = min_y + 2  

                        text_x = max(0, text_x) 
                        text_y = max(0, text_y)

                        # Use the key from REGION_COLORS_FILL that was used for the color
                        text_to_display = str(actual_color_key_used) 
                        draw.text((text_x, text_y), text_to_display, fill=TEXT_COLOR, font=FONT)
                    except Exception as e_text_draw:
                        # Add more context to the error message for text drawing
                        print(f"  Error drawing text '{text_to_display}' for original type '{region_type_from_data}' (labeled as '{actual_color_key_used}'): {e_text_draw}")

                elif not font_warning_printed_this_call and not getattr(draw_filled_regions_on_image, '_global_font_skip_warning_issued', False):
                    print(f"  Skipping text drawing for region (original type '{region_type_from_data}', labeled as '{actual_color_key_used}') as no font could be loaded.")
                    font_warning_printed_this_call = True 
                    # setattr(draw_filled_regions_on_image, '_global_font_skip_warning_issued', True)

            except Exception as e_polygon:
                print(f"  Error processing polygon for region (original type '{region_type_from_data}', labeled as '{actual_color_key_used}'): {e_polygon}")

    combined_image = Image.alpha_composite(base_image_rgba, overlay)
    return combined_image

def process_directories(image_dir, xml_dir, json_dir, output_dir):
    """
    Processes all images, applies overlays from XML and new JSON format, 
    and saves the combined output.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    processed_files = 0
    skipped_images = 0

    for image_filename in os.listdir(image_dir):
        if image_filename.startswith("._"): # Skip macOS hidden files
            print(f"  Skipping hidden macOS file: {image_filename}")
            continue

        if not (image_filename.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff"))):
            print(f"  Skipping non-image file (or unsupported extension): {image_filename}")
            continue
        
        base_name, _ = os.path.splitext(image_filename)
        image_path = os.path.join(image_dir, image_filename)
        
        xml_path = os.path.join(xml_dir, base_name + ".xml")
        json_path_simplified = os.path.join(json_dir, base_name + "_simplified.json")
        json_path_direct = os.path.join(json_dir, base_name + ".json")

        print(f"\nProcessing image: {image_filename}")

        xml_regions = []
        if os.path.exists(xml_path):
            xml_regions = parse_page_xml_regions(xml_path)
            if not xml_regions:
                 print(f"  No regions extracted from XML: {xml_path}")
        else:
            print(f"  Warning: XML file not found at {xml_path}. Skipping XML overlay.")

        json_regions = []
        if os.path.exists(json_path_simplified):
            json_regions = parse_json_regions_simplified(json_path_simplified)
            if not json_regions:
                print(f"  No regions extracted from JSON: {json_path_simplified}")
        elif os.path.exists(json_path_direct):
            print(f"  Found direct JSON match: {json_path_direct}. Attempting to parse.")
            json_regions = parse_json_regions_simplified(json_path_direct) 
            if not json_regions:
                print(f"  No regions extracted from JSON: {json_path_direct}")
        else:
            print(f"  Warning: JSON file not found (tried {json_path_simplified} and {json_path_direct}). Skipping JSON overlay.")

        try:
            original_image = Image.open(image_path)
        except Exception as e:
            print(f"  Error opening image {image_path}: {e}. Skipping.")
            skipped_images += 1
            continue
        
        img_left_rgba = original_image.copy().convert('RGBA') 
        img_right_rgba = original_image.copy().convert('RGBA')

        if xml_regions:
            # Pass REGION_COLORS_FILL as the colors_map argument
            img_left_processed_rgba = draw_filled_regions_on_image(img_left_rgba, xml_regions, REGION_COLORS_FILL)
            print(f"  Applied {len(xml_regions)} filled XML overlays (with corrected labels) to left image.")
        else:
            img_left_processed_rgba = img_left_rgba 

        if json_regions:
            # Pass REGION_COLORS_FILL as the colors_map argument
            img_right_processed_rgba = draw_filled_regions_on_image(img_right_rgba, json_regions, REGION_COLORS_FILL)
            print(f"  Applied {len(json_regions)} filled JSON overlays (with corrected labels) to right image.")
        else:
            img_right_processed_rgba = img_right_rgba 

        img_left_rgb = img_left_processed_rgba.convert('RGB')
        img_right_rgb = img_right_processed_rgba.convert('RGB')
        
        total_width = original_image.width * 2
        height = original_image.height
        
        combined_image = Image.new('RGB', (total_width, height))
        combined_image.paste(img_left_rgb, (0, 0))
        combined_image.paste(img_right_rgb, (original_image.width, 0))

        output_filename = base_name + "_comparison_overlay_labeled.jpg" 
        output_path = os.path.join(output_dir, output_filename)
        try:
            combined_image.save(output_path, "JPEG", quality=90) 
            print(f"  Successfully saved combined image to: {output_path}")
            processed_files += 1
        except Exception as e:
            print(f"  Error saving image {output_path}: {e}")
            
    if processed_files == 0 and skipped_images == 0 and not any(f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")) for f in os.listdir(image_dir)):
         print(f"\nNo image files found in {image_dir}. Please check your input directory.")
    elif processed_files == 0 and skipped_images > 0:
        print(f"\nNo images were successfully processed. {skipped_images} image(s) could not be opened.")
    elif processed_files == 0:
        print(f"\nNo images were processed. This might be due to missing XML/JSON files or no regions found in them.")
    else:
        print(f"\nFinished processing. {processed_files} images were generated.")
    if skipped_images > 0:
        print(f"{skipped_images} image(s) were skipped due to errors during opening.")


if __name__ == '__main__':
    current_script_path = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()

    IMAGE_INPUT_DIR = os.path.join(current_script_path, "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Test for Visual overlay/Image")
    XML_INPUT_DIR = os.path.join(current_script_path, "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Test for Visual overlay/XML") 
    JSON_INPUT_DIR = os.path.join(current_script_path, "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Test for Visual overlay/JSON") 
    OUTPUT_DIR = os.path.join(current_script_path, "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Test for Visual overlay/output")

    for d_path in [IMAGE_INPUT_DIR, XML_INPUT_DIR, JSON_INPUT_DIR, OUTPUT_DIR]:
        actual_path_to_check = d_path 
        if "/Volumes/" in d_path: 
            abs_path_start_index = d_path.find("/Volumes/")
            if abs_path_start_index != -1:
                actual_path_to_check = d_path[abs_path_start_index:]

        if not os.path.exists(actual_path_to_check):
            try:
                os.makedirs(actual_path_to_check)
                print(f"Created directory: {actual_path_to_check}")
            except OSError as e:
                print(f"Error creating directory {actual_path_to_check}: {e}. Please check permissions and path validity.")
    
    print(f"Expecting images in: {IMAGE_INPUT_DIR}")
    print(f"Expecting XML files in: {XML_INPUT_DIR}")
    print(f"Expecting JSON files (new format) in: {JSON_INPUT_DIR}")
    print(f"Output comparison images will be saved to: {OUTPUT_DIR}")
    print("-" * 30)
    
    critical_dirs_exist = True
    for dir_path_str, dir_desc in [(IMAGE_INPUT_DIR, "Image input"), (XML_INPUT_DIR, "XML input"), (JSON_INPUT_DIR, "JSON input")]:
        actual_path_to_check = dir_path_str
        if "/Volumes/" in dir_path_str:
            abs_path_start_index = dir_path_str.find("/Volumes/")
            if abs_path_start_index != -1:
                actual_path_to_check = dir_path_str[abs_path_start_index:]
        
        if not os.path.isdir(actual_path_to_check): 
            print(f"Error: {dir_desc} directory not found or is not a directory: {actual_path_to_check}")
            critical_dirs_exist = False
            
    if critical_dirs_exist:
        process_directories(IMAGE_INPUT_DIR, XML_INPUT_DIR, JSON_INPUT_DIR, OUTPUT_DIR)
    else:
        print("\nProcessing aborted due to missing critical input directories.")