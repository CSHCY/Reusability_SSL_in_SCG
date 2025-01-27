import os
import nbformat
import re

# 获取当前目录下所有 .ipynb 文件
notebook_files = [f for f in os.listdir('.') if f.endswith('.ipynb')]

# 遍历所有 .ipynb 文件
for notebook_file in notebook_files:
    # 获取文件名后缀中的数字部分作为 random_seed
    match = re.search(r'_(\d+)\.ipynb$', notebook_file)
    if not match:
        print(f"跳过文件：{notebook_file}，因为没有找到合适的后缀")
        continue
    random_seed = match.group(1)

    # 读取 .ipynb 文件
    with open(notebook_file, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)

    # 遍历所有单元格，查找并替换 random_seed 的赋值
    updated = False
    for cell in nb.cells:
        if cell.cell_type == 'code' and 'random_seed = ' in cell.source:
            # 使用正则表达式替换 random_seed 的赋值
            cell.source = re.sub(r'random_seed\s*=\s*\d+', f'random_seed = {random_seed}', cell.source)
            updated = True

    # 检查是否有替换发生
    if updated:
        # 保存修改后的 notebook 文件
        with open(notebook_file, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)

        print(f"已更新 {notebook_file} 中的 random_seed 为 {random_seed}")
    else:
        print(f"在 {notebook_file} 中未找到 random_seed 赋值语句，未进行更新")

print("所有文件处理完毕。")
