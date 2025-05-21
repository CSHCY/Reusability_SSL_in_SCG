import os
import subprocess
import re

print(os.getcwd())
# Print all files in current directory to debug pattern matching
print("Files in current directory:", os.listdir())

# 设置环境
kernel_path = "~/miniconda3/envs/ssl/bin/python"
notebook_files = []

# Screen for specific notebook patterns using regex
patterns = [
    r"barlow_twins_zero_shot_\d+\.ipynb$",
    r"GP_mask_zero_shot_\d+\.ipynb$", 
    r"random_mask_fine_tune_\d+\.ipynb$"
]

print("Looking for patterns:", patterns)
for pattern in patterns:
    for file in os.listdir():
        if re.search(pattern, file):  # Changed from re.match to re.search
            print(f"Pattern '{pattern}' matched file:", file)
            notebook_files.append(file)

print(f"Found {len(notebook_files)} matching notebooks: {notebook_files}")

for notebook in notebook_files:
    print(f"Executing {notebook}...")
    
    # 执行 notebook
    execute_command = [
        "jupyter", "nbconvert", "--to", "notebook",
        "--execute", "--inplace", notebook,
        "--ExecutePreprocessor.kernel_name=ssl",
    ]
    
    try:
        subprocess.run(execute_command, check=True)
        print(f"Successfully executed {notebook}.")
        
    except subprocess.CalledProcessError as e:
        print(f"Error executing {notebook}: {e}")
    
    # 清理内存并释放 kernel
    subprocess.run(["jupyter", "notebook", "stop"])

print("All notebooks executed.")
