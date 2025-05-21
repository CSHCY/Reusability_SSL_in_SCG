import os
import re
import nbformat

# Directory containing the neocortex files
directory = "./"  # Update this path if needed

# Regex patterns to match `random_seed=<value>` and `random_state=<value>`
random_seed_pattern = re.compile(r"random_seed\s*=\s*\d+")
random_state_pattern = re.compile(r"random_state\s*=\s*\d+")

# Loop through all .ipynb files with "neocortex" in their names
for file_name in os.listdir(directory):
    if file_name.endswith(".ipynb") and "neocortex" in file_name:
        file_path = os.path.join(directory, file_name)
        print(f"Processing {file_name}...")

        # Extract the number from the file name
        number_in_filename = file_name.split("_")[-1].replace(".ipynb", "")
        if not number_in_filename.isdigit():
            print(f"Warning: Could not extract a valid number from {file_name}. Skipping...")
            continue
        new_value = number_in_filename

        # Load the notebook
        with open(file_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)

        modified = False  # Flag to track if we modified the file

        # Iterate through cells in the notebook
        for cell in notebook.cells:
            if cell.cell_type == "code":
                # Check and replace `random_seed=<value>` and `random_state=<value>`
                lines = cell.source.splitlines()
                new_lines = []
                for line in lines:
                    if random_seed_pattern.search(line):
                        modified = True
                        line = random_seed_pattern.sub(f"random_seed={new_value}", line)
                    if random_state_pattern.search(line):
                        modified = True
                        line = random_state_pattern.sub(f"random_state={new_value}", line)
                    new_lines.append(line)
                cell.source = "\n".join(new_lines)

        # Save the modified notebook
        if modified:
            with open(file_path, "w", encoding="utf-8") as f:
                nbformat.write(notebook, f)
            print(f"Modified {file_name} and saved changes.")
        else:
            print(f"No changes needed for {file_name}.")
