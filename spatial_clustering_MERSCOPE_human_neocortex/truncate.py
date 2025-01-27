import os
import nbformat

# Directory containing the neocortex files
directory = "./"  # Update this path if needed

# Loop through all .ipynb files with "neocortex" in their names
for file_name in os.listdir(directory):
    if file_name.endswith(".ipynb") and "neocortex" in file_name:
        file_path = os.path.join(directory, file_name)
        print(f"Processing {file_name}...")

        # Load the notebook
        with open(file_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)

        modified = False  # Flag to track if we modified the file

        # Iterate through cells in the notebook
        for cell in notebook.cells:
            if cell.cell_type == "code" and "plt.close()" in cell.source:
                # Find the index of plt.close() and truncate the code after it
                code_lines = cell.source.splitlines()
                for idx, line in enumerate(code_lines):
                    if "plt.close()" in line:
                        cell.source = "\n".join(code_lines[:idx + 1])
                        modified = True
                        break

        # Save the modified notebook
        if modified:
            with open(file_path, "w", encoding="utf-8") as f:
                nbformat.write(notebook, f)
            print(f"Modified {file_name} and saved changes.")
        else:
            print(f"No changes needed for {file_name}.")
