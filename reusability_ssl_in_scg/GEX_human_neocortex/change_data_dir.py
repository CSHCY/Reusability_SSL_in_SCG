import os
import nbformat
import re

# Get all .ipynb files in current directory
notebook_files = [f for f in os.listdir('.') if f.endswith('.ipynb')]

# Process each notebook file
for notebook_file in notebook_files:
    # Read the notebook
    with open(notebook_file, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)

    # Flag to track if we made changes
    updated = False
    
    # Look through cells for data_dir assignment
    for cell in nb.cells:
        if cell.cell_type == 'code' and 'data_dir = ' in cell.source:
            # Replace data_dir assignment with new path
            cell.source = re.sub(
                r'data_dir\s*=\s*[\'"].*[\'"]',
                'data_dir = \'../../dataset/GEX_human_neocortex_filtered.h5ad\'',
                cell.source
            )
            updated = True

    # Save changes if we updated anything
    if updated:
        with open(notebook_file, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        print(f"Updated data_dir in {notebook_file}")
    else:
        print(f"No data_dir assignment found in {notebook_file}")

print("Finished processing all notebook files.")
