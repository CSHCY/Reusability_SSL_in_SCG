import os
import glob
import re

# Get all ipynb files in current directory that match pattern
notebook_directory = './'
notebook_files = [os.path.join(notebook_directory, f) for f in os.listdir(notebook_directory) 
                 if f.endswith('.ipynb')]

for notebook_file in notebook_files:
    # Read notebook content
    with open(notebook_file, 'r') as f:
        content = f.read()
    notebook_name = os.path.basename(notebook_file)
    # Extract method name from notebook name using regex pattern
    method_name_match = re.search(r'tabula_sapiens_(.*?)_\d+', notebook_name)
    # Extract method name from notebook_name assignment
    if method_name_match:
        method_name = method_name_match.group(1)
        
        # Replace barlow_twins_fine_tune with extracted method name in output_dir
        new_content = re.sub(
            r'(output_dir\s*=\s*os\.path\.join\(\'./prediction_results\',\s*f\')barlow_twins_fine_tune(_seed_)',
            rf'\1{method_name}\2',
            content
        )
        
        # Write back to file if changes were made
        if new_content != content:
            with open(notebook_file, 'w') as f:
                f.write(new_content)
            print(f"Updated {notebook_file}: Changed barlow_twins_fine_tune to {method_name}")
        else:
            print(f"No changes needed in {notebook_file}")
    else:
        print(f"Could not find method name in {notebook_file}")
