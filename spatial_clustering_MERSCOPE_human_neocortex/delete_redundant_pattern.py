import os
import nbformat
import re

# Function to check and fix redundant "]" in code lines
def fix_redundant_brackets(cell):
    # Pattern to match and fix lines with redundant "]"
    redundant_bracket_pattern = re.compile(r"(\]\])")
    fixed_lines = []

    for line in cell.source.splitlines():
        if redundant_bracket_pattern.search(line):
            # Replace redundant "]]" with "]"
            fixed_line = redundant_bracket_pattern.sub("]", line)
            print(f"Fixed redundant brackets in line:\nBefore: {line}\nAfter: {fixed_line}\n")
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)
    
    # Update the cell's source
    cell.source = "\n".join(fixed_lines)

# Process all notebooks in the current directory
directory = "./"
for file_name in os.listdir(directory):
    if file_name.endswith(".ipynb"):
        file_path = os.path.join(directory, file_name)

        # Open the notebook
        with open(file_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)

        # Process the last but one code cell if it exists
        if len(notebook.cells) >= 2:
            last_but_one_cell = notebook.cells[-2]
            if last_but_one_cell.cell_type == "code":
                fix_redundant_brackets(last_but_one_cell)

        # Save the modified notebook
        with open(file_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)

        print(f"Processed and saved: {file_name}")
