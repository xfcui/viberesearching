import os
import sys
import argparse
import subprocess
import shutil

def check_package(package_name):
    """Check if a python package is installed."""
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False

def convert_with_marker_cli(input_path, output_dir):
    """Convert PDF using marker_single CLI tool."""
    print("Attempting conversion with marker-pdf CLI...")
    try:
        # Check if marker_single is in PATH
        marker_single_path = shutil.which("marker_single")
        if not marker_single_path:
            print("marker_single CLI tool not found in PATH.")
            return False

        # Run marker_single
        cmd = [
            marker_single_path,
            input_path,
            "--output_format", "markdown",
            "--output_dir", output_dir
        ]
        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("Successfully converted PDF using marker-pdf CLI.")
            return True
        else:
            print(f"marker-pdf CLI failed with exit code {result.returncode}.")
            print(f"Error output:\n{result.stderr}")
            return False
    except Exception as e:
        print(f"Error running marker-pdf CLI: {e}")
        return False

def convert_with_marker_api(input_path, output_dir, output_md_path):
    """Convert PDF using marker-pdf Python API."""
    print("Attempting conversion with marker-pdf Python API...")
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered

        print("Loading marker-pdf models (this may take a moment)...")
        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(input_path)
        text, _, images = text_from_rendered(rendered)

        # Write markdown
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(text)

        # Save images if any
        if images:
            images_dir = os.path.join(output_dir, "images")
            os.makedirs(images_dir, exist_ok=True)
            for img_name, img_data in images.items():
                img_path = os.path.join(images_dir, img_name)
                # Check if img_data is bytes or PIL Image
                if hasattr(img_data, "save"):
                    img_data.save(img_path)
                else:
                    with open(img_path, "wb") as img_f:
                        img_f.write(img_data)
            print(f"Saved {len(images)} images to {images_dir}")

        print("Successfully converted PDF using marker-pdf Python API.")
        return True
    except Exception as e:
        print(f"Error running marker-pdf Python API: {e}")
        return False

def convert_with_pymupdf4llm(input_path, output_md_path):
    """Convert PDF using pymupdf4llm as fallback."""
    print("Attempting fallback conversion with pymupdf4llm...")
    try:
        import pymupdf4llm
        md_text = pymupdf4llm.to_markdown(input_path)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        print("Successfully converted PDF using pymupdf4llm fallback.")
        return True
    except Exception as e:
        print(f"Error running pymupdf4llm fallback: {e}")
        return False

def convert_with_pdfplumber(input_path, output_md_path):
    """Convert PDF using pdfplumber as fallback."""
    print("Attempting fallback conversion with pdfplumber...")
    try:
        import pdfplumber
        markdown_content = []
        with pdfplumber.open(input_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"Extracting text from {total_pages} pages...")
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    markdown_content.append(f"## Page {i+1}\n\n{text}")
                else:
                    markdown_content.append(f"## Page {i+1}\n\n*[Empty Page or Scanned Image]*")
        
        full_text = "\n\n".join(markdown_content)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        print("Successfully converted PDF using pdfplumber fallback.")
        return True
    except Exception as e:
        print(f"Error running pdfplumber fallback: {e}")
        return False

def convert_with_pypdf(input_path, output_md_path):
    """Convert PDF using pypdf as fallback."""
    print("Attempting fallback conversion with pypdf...")
    try:
        import pypdf
        reader = pypdf.PdfReader(input_path)
        total_pages = len(reader.pages)
        print(f"Extracting text from {total_pages} pages...")
        markdown_content = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                markdown_content.append(f"## Page {i+1}\n\n{text}")
            else:
                markdown_content.append(f"## Page {i+1}\n\n*[Empty Page or Scanned Image]*")
        
        full_text = "\n\n".join(markdown_content)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        print("Successfully converted PDF using pypdf fallback.")
        return True
    except Exception as e:
        print(f"Error running pypdf fallback: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown using marker-pdf with fallback options.")
    parser.add_argument("--input", "-i", required=True, help="Path to the input PDF file.")
    parser.add_argument("--output", "-o", help="Path to the output Markdown file.")
    parser.add_argument("--output-dir", "-d", help="Directory to save output files (markdown, images).")
    parser.add_argument("--fallback", action="store_true", help="Force fallback mode (skip marker-pdf).")
    
    args = parser.parse_args()
    
    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"Error: Input file does not exist: {input_path}")
        sys.exit(1)
        
    # Determine output directory and output markdown path
    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        output_dir = os.path.dirname(input_path)
        
    os.makedirs(output_dir, exist_ok=True)
    
    filename_without_ext = os.path.splitext(os.path.basename(input_path))[0]
    
    if args.output:
        output_md_path = os.path.abspath(args.output)
    else:
        output_md_path = os.path.join(output_dir, f"{filename_without_ext}.md")
        
    success = False
    
    if not args.fallback:
        # 1. Try marker-pdf CLI
        if convert_with_marker_cli(input_path, output_dir):
            success = True
        # 2. Try marker-pdf Python API
        elif check_package("marker") and convert_with_marker_api(input_path, output_dir, output_md_path):
            success = True
            
    if not success:
        print("\nmarker-pdf is not available or failed. Trying fallbacks...")
        # 3. Try pymupdf4llm
        if check_package("pymupdf4llm"):
            if convert_with_pymupdf4llm(input_path, output_md_path):
                success = True
        # 4. Try pdfplumber
        if not success and check_package("pdfplumber"):
            if convert_with_pdfplumber(input_path, output_md_path):
                success = True
        # 5. Try pypdf
        if not success and check_package("pypdf"):
            if convert_with_pypdf(input_path, output_md_path):
                success = True
                
    if success:
        print(f"\nSuccess! Markdown output saved to: {output_md_path}")
        sys.exit(0)
    else:
        print("\nError: All conversion methods failed.")
        print("Please install one of the following packages and try again:")
        print("  - For high-fidelity conversion (tables, math, layout):")
        print("    pip install marker-pdf")
        print("  - For lightweight text extraction:")
        print("    pip install pdfplumber  (or)  pip install pypdf")
        sys.exit(1)

if __name__ == "__main__":
    main()
