import os
import shutil

# 获取当前目录下所有 .ipynb 文件
notebook_files = [f for f in os.listdir('.') if f.endswith('PCA.ipynb') or f.endswith('supervised.ipynb')]

# 定义后缀列表
suffixes = ["_42", "_476", "_761", "_3407", "_9824"]

# 遍历所有 .ipynb 文件
for notebook_file in notebook_files:
    # 创建副本
    for suffix in suffixes:
        new_file_name = f"{os.path.splitext(notebook_file)[0]}{suffix}.ipynb"
        shutil.copy(notebook_file, new_file_name)

print("已成功为每个 .ipynb 文件创建四个副本，且添加了后缀。")
