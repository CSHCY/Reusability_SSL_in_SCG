import os
import subprocess
import glob

print(os.getcwd())
# 设置环境
kernel_path = "~/miniconda3/envs/cellcharter/bin/python"
notebook_files = glob.glob("./*.ipynb")

for notebook in notebook_files:
    if "cellcharter" in notebook:  # 仅执行包含 "stagate" 的文件
        print(f"Executing {notebook}...")
        
        # 执行 notebook
        execute_command = [
            "jupyter", "nbconvert", "--to", "notebook",
            "--execute", "--inplace", notebook,
            "--ExecutePreprocessor.kernel_name=cellcharter",
        ]
        
        try:
            subprocess.run(execute_command, check=True)
            print(f"Successfully executed {notebook}.")
            
        except subprocess.CalledProcessError as e:
            print(f"Error executing {notebook}: {e}")
        
        # 清理内存并释放 kernel
        subprocess.run(["jupyter", "notebook", "stop"])

print("All selected notebooks executed.")
