import os
import nbformat
import re

# Check for the existence of "random_seed" or "random_state" in the notebook
def find_seed_or_state(notebook):
    for cell in notebook.cells:
        if cell.cell_type == "code":
            if re.search(r"random_seed\s*=\s*\d+", cell.source):
                return "random_seed"
            if re.search(r"random_state\s*=\s*\d+", cell.source):
                return "random_state"
    return None

# Modify the last but one code cell
def process_last_but_one_cell(cell, seed_or_state):
    # Patterns to match obs and obsm assignments with "_SSL_"
    obs_pattern = re.compile(r"new_adata\.obs\[\s*f?[\"'].*_SSL_.*[\"']\s*\]")
    obsm_pattern = re.compile(r"new_adata\.obsm\[\s*f?[\"'].*_SSL_.*[\"']\s*\]")

    # Replace "_SSL_" with ""
    modified_lines = []
    for line in cell.source.splitlines():
        if obs_pattern.search(line) or obsm_pattern.search(line):
            # Remove "_SSL_" from the key inside obs and obsm
            line = re.sub(r"_SSL", "", line)

            # Ensure "f" is present before the string in brackets
            line = re.sub(r"new_adata\.(obs|obsm)\[\s*[\"']", r"new_adata.\1[f'", line)

            # Add "_{seed_or_state}" at the end of the key
            line = re.sub(r"([\"'])\s*\]", rf"_{{{seed_or_state}}}']]", line)

        modified_lines.append(line)

    # Update the cell's source with the modified lines
    cell.source = "\n".join(modified_lines)

# Process all notebooks in the current directory
directory = "./"
for file_name in os.listdir(directory):
    if file_name.endswith(".ipynb"):
        file_path = os.path.join(directory, file_name)

        # Open the notebook
        with open(file_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)

        # Identify "random_seed" or "random_state" variable
        seed_or_state = find_seed_or_state(notebook)
        if not seed_or_state:
            print(f"No random_seed or random_state variable found in {file_name}. Skipping.")
            continue

        # Process the last but one code cell
        if len(notebook.cells) >= 2:
            last_but_one_cell = notebook.cells[-2]
            if last_but_one_cell.cell_type == "code":
                process_last_but_one_cell(last_but_one_cell, seed_or_state)

        # Save the modified notebook
        with open(file_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)

        print(f"Processed and saved: {file_name}")
