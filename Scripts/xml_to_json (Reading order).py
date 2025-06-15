import os
import xml.etree.ElementTree as ET
import json
import re

def extract_text_from_xml(xml_file_path):
    """
    Parses an XML file representing a document scan and extracts text regions
    and their content into a JSON-like structure.

    Args:
        xml_file_path (str): The path to the input XML file.

    Returns:
        list: A list of dictionaries, where each dictionary represents a
              text region with its 'type' and 'text'. Returns an empty
              list if no processable text regions are found.
    """
    # Prepare separate containers: one for the main reading order and one for marginalia that we will append after everything else
    main_regions = []
    marginalia_regions = []
    
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
    except ET.ParseError:
        print(f"Error parsing XML file: {xml_file_path}. Skipping.")
        return []

    # Define the namespace
    ns = {'page': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15'}

    page_element = root.find('page:Page', ns)
    if page_element is None:
        # Handle cases where Page element might be missing or named differently (though unlikely for PAGE XML)
        # Or if the XML is empty like NL-HaNA_1.04.02_7923_0006.xml
        return []

    for text_region in page_element.findall('page:TextRegion', ns):
        custom_attr = text_region.get('custom', '')
        
        # Extract region type using regex to find "type:actual_type;"
        match = re.search(r'type:\s*([^;}]+)', custom_attr)
        if not match:
            continue 
        region_type = match.group(1).strip()
        # Skip regions that are explicitly labelled as "unknown"
        if region_type.lower() == "unknown":
            continue

        region_texts = []
        text_lines = text_region.findall('page:TextLine', ns)

        if not text_lines: # Check for text directly under TextRegion if no TextLines
            text_equiv_direct = text_region.find('page:TextEquiv/page:Unicode', ns)
            if text_equiv_direct is not None and text_equiv_direct.text:
                region_texts.append(text_equiv_direct.text.strip())
        else:
            for text_line in text_lines:
                # Prioritize full TextEquiv for the line
                line_text_equiv = text_line.find('page:TextEquiv/page:Unicode', ns)
                if line_text_equiv is not None and line_text_equiv.text:
                    line_text = line_text_equiv.text.strip()
                    if line_text: # Ensure non-empty text
                        region_texts.append(line_text)
                else:
                    # Fallback to concatenating words if no full line TextEquiv
                    word_texts = []
                    for word in text_line.findall('page:Word', ns):
                        word_text_equiv = word.find('page:TextEquiv/page:Unicode', ns)
                        if word_text_equiv is not None and word_text_equiv.text:
                            word_text = word_text_equiv.text.strip()
                            if word_text: # Ensure non-empty word text
                                word_texts.append(word_text)
                    if word_texts:
                        region_texts.append(" ".join(word_texts))
        
        if region_texts:
            full_region_text = " ".join(region_texts)
            region_entry = {
                "type": region_type,
                "text": full_region_text
            }
            # Keep marginalia separate so it can be appended to the end of the JSON output
            if region_type.lower() == "marginalia":
                marginalia_regions.append(region_entry)
            else:
                main_regions.append(region_entry)
            
    # First return the main reading‑order regions, then all marginalia regions
    return main_regions + marginalia_regions

def convert_xml_directory_to_json(input_dir, output_dir):
    """
    Converts all XML files in an input directory to JSON format and
    saves them in an output directory.

    Args:
        input_dir (str): The directory containing input XML files.
        output_dir (str): The directory where output JSON files will be saved.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    for filename in os.listdir(input_dir):
        if filename.endswith(".xml"):
            xml_file_path = os.path.join(input_dir, filename)
            print(f"Processing {xml_file_path}...")
            
            json_data = extract_text_from_xml(xml_file_path)
            
            base_filename = os.path.splitext(filename)[0]
            json_file_path = os.path.join(output_dir, f"{base_filename}.json")
            
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            print(f"Successfully converted to {json_file_path}")

if __name__ == '__main__':
    # --- Configuration ---
    # IMPORTANT: Replace these with the actual paths to your directories.
    # For example, if your XML files are in a folder named "xml_scans" on your Desktop,
    # and you want to save JSON files to a folder named "json_output" on your Desktop:
    INPUT_DIRECTORY = "/Users/gavinl/Desktop/7924/page"  # macOS/Linux example
    OUTPUT_DIRECTORY = "/Volumes/Extreme SSD/Python_Projects/Layout Feature Extraction with LLMs/7924_reading_order" # macOS/Linux example
    # INPUT_DIRECTORY = "C:\\Users\\yourusername\\Desktop\\xml_scans"  # Windows example
    # OUTPUT_DIRECTORY = "C:\\Users\\yourusername\\Desktop\\json_output" # Windows example
    
    # Using placeholder directories for demonstration. 
    # Create these directories and place your XML files in INPUT_DIRECTORY.
    current_script_path = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
    # INPUT_DIRECTORY = os.path.join(current_script_path, "input_xml_files") 
    # OUTPUT_DIRECTORY = os.path.join(current_script_path, "output_json_files")

    # --- Create dummy input directory and files for testing if they don't exist ---
    # This part is for making the script runnable for demonstration.
    # You should replace INPUT_DIRECTORY with your actual data folder.
    if not os.path.exists(INPUT_DIRECTORY):
        os.makedirs(INPUT_DIRECTORY)
        print(f"Created dummy input directory: {INPUT_DIRECTORY}")
        print(f"Please place your XML files in {INPUT_DIRECTORY} to run the script.")
    
    # Example: Create a dummy XML file if input directory is empty for testing purposes
    # You would normally have your actual XML files here.
    if os.path.exists(INPUT_DIRECTORY) and not any(f.endswith('.xml') for f in os.listdir(INPUT_DIRECTORY)):
        dummy_xml_content = """<?xml version='1.0' encoding='UTF-8'?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
  <Page imageFilename="dummy.jpg" imageWidth="1000" imageHeight="1500">
    <TextRegion id="region_1" custom="structure {type:paragraph;}">
      <TextLine id="line_1_1">
        <TextEquiv>
          <Unicode>This is a sample paragraph.</Unicode>
        </TextEquiv>
      </TextLine>
    </TextRegion>
    <TextRegion id="region_2" custom="structure {type:marginalia;}">
      <TextLine id="line_2_1">
        <Word id="word_2_1_1"><TextEquiv><Unicode>Marginal</Unicode></TextEquiv></Word>
        <Word id="word_2_1_2"><TextEquiv><Unicode>note.</Unicode></TextEquiv></Word>
      </TextLine>
    </TextRegion>
    <TextRegion id="region_3" custom="structure {type:page-number;}">
      {/* This region has no text lines/text and should be skipped if text is the criteria */}
    </TextRegion>
  </Page>
</PcGts>"""
        with open(os.path.join(INPUT_DIRECTORY, "dummy_example.xml"), "w", encoding="utf-8") as df:
            df.write(dummy_xml_content)
        print(f"Created a dummy XML file in {INPUT_DIRECTORY} for demonstration.")

    if os.path.exists(INPUT_DIRECTORY) and any(f.endswith('.xml') for f in os.listdir(INPUT_DIRECTORY)):
         convert_xml_directory_to_json(INPUT_DIRECTORY, OUTPUT_DIRECTORY)
    else:
        print(f"Input directory {INPUT_DIRECTORY} does not exist or contains no XML files. Please check the path and contents.")