import imgkit
import os

# Path to wkhtmltoimage (Ensure this path is correct)
wkhtmltoimage_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltoimage.exe"

# Configuration for imgkit
img_config = imgkit.config(wkhtmltoimage=wkhtmltoimage_path)

# HTML file path (Ensure the file exists)
html_file = r"C:\Users\Bhoomi Vaishya\Documents\Java Practice\newprojectpython\templates\weekly_graph.html"

# Output image file path
output_file = r"C:\Users\Bhoomi Vaishya\Documents\Java Practice\newprojectpython\templates\weekly_graph.png"

# Ensure the HTML file exists
if not os.path.exists(html_file):
    raise FileNotFoundError(f"HTML file not found: {html_file}")

# Convert HTML to image
try:
    imgkit.from_file(
        html_file,
        output_file,
        config=img_config,
        options={
            "enable-local-file-access": "",  # Allows local file access
            "quiet": ""  # Suppresses warnings
        }
    )
    print(f"Conversion successful! Image saved at: {output_file}")

except OSError as e:
    print(f"Error: {e}")
