import os
import xml.etree.ElementTree as ET
import json
import re
from shapely.geometry import LineString, Polygon # Added for simplification

# --- Configuration ---
# Adjust this tolerance value to control the level of simplification.
# Higher values mean more simplification (fewer points, less detail).
# Lower values mean less simplification (more points, more detail).
# You'll likely need to experiment with this value based on your specific documents.
SIMPLIFICATION_TOLERANCE = 200.0 # Example value, adjust as needed

def parse_points_string(points_str):
    """
    Parses a string of space-separated 'x,y' coordinate pairs into a list of [x, y] tuples.
    Example input: "10,20 30,40 50,60"
    Example output: [(10, 20), (30, 40), (50, 60)]
    """
    coordinates = []
    if not points_str:
        return coordinates
    pairs = points_str.split(' ')
    for pair in pairs:
        try:
            x_str, y_str = pair.split(',')
            coordinates.append((float(x_str), float(y_str)))
        except ValueError:
            # Handle potential errors in coordinate string format, e.g., empty strings if there are double spaces
            # print(f"Warning: Could not parse point pair '{pair}' in '{points_str}'. Skipping.")
            continue
    return coordinates

def simplify_coordinates(coords_list, tolerance):
    """
    Simplifies a list of [x,y] coordinates using the Ramer-Douglas-Peucker algorithm.
    Ensures the polygon is closed before simplification.
    """
    if not coords_list or len(coords_list) < 3: # Need at least 3 points for a polygon
        return coords_list

    # Ensure the polygon is closed (first and last points are the same)
    # This is important for shapely.geometry.Polygon and for sensible simplification of a closed region
    closed_coords_list = list(coords_list) # Make a copy
    if closed_coords_list[0] != closed_coords_list[-1]:
        closed_coords_list.append(closed_coords_list[0])
    
    if len(closed_coords_list) < 3: # Still not enough points after potential closure
        return closed_coords_list


    try:
        # For simplification, we can treat the boundary as a LineString.
        # If the original shape is a valid Polygon, simplify its exterior.
        # Using LineString is generally more robust for potentially "messy" input coordinates from tracing.
        line = LineString(closed_coords_list)
        simplified_line = line.simplify(tolerance, preserve_topology=True)
        
        # Get coordinates from the simplified geometry
        # The result might be a LineString or MultiLineString (if simplification breaks it)
        # For simplicity, we'll assume it remains a single LineString representing the polygon boundary
        if simplified_line.is_empty:
            return []
        
        simplified_coords = list(simplified_line.coords)

        # Ensure the simplified polygon is also explicitly closed in the output list
        if simplified_coords and simplified_coords[0] != simplified_coords[-1]:
            simplified_coords.append(simplified_coords[0])
            
        return [[round(pt[0], 2), round(pt[1], 2)] for pt in simplified_coords] # Round for cleaner JSON

    except Exception as e:
        print(f"Error during simplification: {e}. Returning original (closed) coordinates.")
        # Return the closed (but not simplified) coordinates in case of an error
        return [[round(pt[0], 2), round(pt[1], 2)] for pt in closed_coords_list]


def extract_data_from_xml(xml_file_path):
    """
    Parses a PAGE XML file, extracts text regions with their type, text,
    and simplified polygon coordinates.

    Args:
        xml_file_path (str): The path to the input XML file.

    Returns:
        list: A list of dictionaries, where each dictionary represents a
              text region with its 'type', 'text', and 'simplified_polygon'.
              Returns an empty list if no processable regions are found.
    """
    json_output = []
    
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
    except ET.ParseError:
        print(f"Error parsing XML file: {xml_file_path}. Skipping.")
        return []

    # Define the namespace (assuming PAGE XML as per your samples)
    # The namespace URI might vary slightly in different versions of PAGE XML.
    # Check your XML files if you encounter issues.
    ns_uri = root.tag.split('}')[0][1:] if '}' in root.tag else ''
    ns = {'page': ns_uri} if ns_uri else {}
    
    # Find the Page element
    page_element_name = 'Page'
    if ns:
        page_element_name = f"{{{ns['page']}}}{page_element_name}"
    else: # If no namespace is detected at root, try finding Page without it (less common for PAGE XML)
        page_element_name = 'Page'

    page_element = root.find(page_element_name, ns)

    if page_element is None:
         # If root is PcGts, Page might be a direct child without prefix if ns wasn't properly caught or used by find
        if root.tag.endswith("PcGts"): # Common root tag for PAGE XML
            page_element = root.find('page:Page', {'page': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15'}) # Try with common PAGE ns
            if page_element is None:
                 page_element = root.find('Page') # Try without explicit namespace mapping in find

        if page_element is None:
            print(f"Could not find Page element in {xml_file_path}. Skipping.")
            return []


    # Iterate through different types of regions if necessary.
    # For now, focusing on TextRegion as per original script and typical PAGE XML.
    region_types_to_process = ['TextRegion', 'ImageRegion', 'LineDrawingRegion', 'GraphicRegion', 'TableRegion', 'ChartRegion', 'SeparatorRegion', 'MathsRegion', 'NoiseRegion', 'FrameRegion'] # Add other region types as needed

    for region_tag_name in region_types_to_process:
        
        find_query = f'page:{region_tag_name}' if ns else region_tag_name
        
        for region_element in page_element.findall(find_query, ns):
            region_data = {}
            
            # Get region type from 'custom' attribute (as in original script) or tag name
            custom_attr = region_element.get('custom', '')
            match = re.search(r"structure {type:([^;}]+);?", custom_attr)
            if match:
                region_data['type'] = match.group(1)
            else:
                region_data['type'] = region_tag_name # Default to the tag name if no custom type

            # Extract text content (as in original script)
            region_text_parts = []
            for text_line in region_element.findall('.//page:TextLine', ns) if ns else region_element.findall('.//TextLine'):
                for text_equiv in text_line.findall('.//page:TextEquiv', ns) if ns else text_line.findall('.//TextEquiv'):
                    unicode_text_element = text_equiv.find('page:Unicode', ns) if ns else text_equiv.find('Unicode')
                    if unicode_text_element is not None and unicode_text_element.text:
                        region_text_parts.append(unicode_text_element.text.strip())
            region_data['text'] = " ".join(region_text_parts).strip()

            # Extract and simplify coordinates
            coords_element = region_element.find('page:Coords', ns) if ns else region_element.find('Coords')
            if coords_element is not None and coords_element.get('points'):
                points_str = coords_element.get('points')
                original_coords = parse_points_string(points_str)
                if original_coords:
                    simplified_poly_coords = simplify_coordinates(original_coords, SIMPLIFICATION_TOLERANCE)
                    region_data['simplified_polygon'] = simplified_poly_coords
                else:
                    region_data['simplified_polygon'] = [] # No valid points found
            else:
                region_data['simplified_polygon'] = [] # No Coords element or points attribute

            # Only add region if it has a type (and optionally text or polygon)
            if region_data.get('type'):
                 json_output.append(region_data)
                 
    return json_output

def main():
    """
    Main function to process all XML files in the input directory and
    save the extracted data as JSON files in the output directory.
    """
    # --- Directories ---
    # Make sure these directories exist or are created before running.
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    # Ensure INPUT_DIRECTORY and OUTPUT_DIRECTORY are correctly joined if they are not absolute paths
    # If the paths provided by the user are absolute, os.path.join will handle them correctly.
    # If they are relative, they will be relative to current_script_dir.
    INPUT_DIRECTORY = "/Users/gavinl/Desktop/7924/page" 
    OUTPUT_DIRECTORY = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Simplified Page Regions (JSON)/7924"

    # If the provided paths are intended to be relative to the script, use this:
    # INPUT_DIRECTORY = os.path.join(current_script_dir, "Users/gavinl/Desktop/7924/page") 
    # OUTPUT_DIRECTORY = os.path.join(current_script_dir, "Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/Data/Simplified Page Regions (JSON)/7924")


    if not os.path.exists(INPUT_DIRECTORY):
        print(f"Input directory '{INPUT_DIRECTORY}' does not exist. Please create it and add XML files.")
        # For demonstration, let's create dummy input if it doesn't exist.
        # You should place your actual XML files here.
        os.makedirs(INPUT_DIRECTORY, exist_ok=True)
        # Create a dummy XML file for testing if the directory was just created and is empty
        if not os.listdir(INPUT_DIRECTORY):
            dummy_xml_filename = "dummy_example_page.xml"
            dummy_xml_content = """<?xml version='1.0' encoding='UTF-8'?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">
  <Metadata>
    <Creator>DummyCreator</Creator>
    <Created>2023-01-01T00:00:00</Created>
    <LastChange>2023-01-01T00:00:00</LastChange>
  </Metadata>
  <Page imageFilename="dummy.jpg" imageWidth="2000" imageHeight="3000">
    <TextRegion id="r1" custom="structure {type:paragraph;}">
      <Coords points="100,100 100,200 600,200 600,190 650,150 600,110 600,100"/>
      <TextLine id="r1_l1">
        <Coords points="110,120 110,180 590,180 590,120"/>
        <TextEquiv>
          <Unicode>This is a sample paragraph with a slightly complex boundary.</Unicode>
        </TextEquiv>
      </TextLine>
    </TextRegion>
    <TextRegion id="r2" custom="structure {type:heading;}">
      <Coords points="100,300 500,300 500,350 100,350 90,325"/>
       <TextLine id="r2_l1">
        <Coords points="110,310 490,310 490,340 110,340"/>
        <TextEquiv>
          <Unicode>A Simple Heading</Unicode>
        </TextEquiv>
      </TextLine>
    </TextRegion>
    <ImageRegion id="img1">
        <Coords points="700,50 700,450 1200,450 1200,50"/>
    </ImageRegion>
  </Page>
</PcGts>"""
            with open(os.path.join(INPUT_DIRECTORY, dummy_xml_filename), "w", encoding="utf-8") as df:
                df.write(dummy_xml_content)
            print(f"Created a dummy XML file for testing: {os.path.join(INPUT_DIRECTORY, dummy_xml_filename)}")


    if not os.path.exists(OUTPUT_DIRECTORY):
        os.makedirs(OUTPUT_DIRECTORY)
        print(f"Created output directory: {OUTPUT_DIRECTORY}")

    print(f"Processing XML files from: {INPUT_DIRECTORY}")
    print(f"Saving JSON files to: {OUTPUT_DIRECTORY}")
    print(f"Simplification Tolerance set to: {SIMPLIFICATION_TOLERANCE}")
    print("-" * 30)

    processed_files = 0
    for filename in os.listdir(INPUT_DIRECTORY):
        if filename.endswith(".xml"):
            xml_file_path = os.path.join(INPUT_DIRECTORY, filename)
            print(f"Processing file: {filename}...")
            
            extracted_data = extract_data_from_xml(xml_file_path)
            
            if extracted_data:
                base_filename = os.path.splitext(filename)[0]
                # --- FIX: Added .json extension to the output filename ---
                json_file_path = os.path.join(OUTPUT_DIRECTORY, f"{base_filename}.json") 
                
                try:
                    with open(json_file_path, 'w', encoding='utf-8') as json_file:
                        json.dump(extracted_data, json_file, indent=4, ensure_ascii=False)
                    print(f"Successfully saved simplified data to: {json_file_path}")
                    processed_files +=1
                except IOError as e:
                    print(f"Error writing JSON file {json_file_path}: {e}")
            else:
                print(f"No data extracted or to save for {filename}.")
            print("-" * 30)

    print(f"Processing complete. Processed {processed_files} XML file(s).")

if __name__ == "__main__":
    # Before running:
    # 1. Make sure you have the 'shapely' library installed.
    #    If not, run: pip install shapely
    # 2. Create a folder named "input_xml_files" in the same directory as this script 
    #    OR update INPUT_DIRECTORY to your actual path.
    # 3. Place your XML files (e.g., NL-HaNA_1.04.02_7923_0171.xml) into the input folder.
    # 4. An output folder (as specified in OUTPUT_DIRECTORY) will be created by the script if it doesn't exist.
    main()