import nbformat
import os

# 获取当前目录下所有 .ipynb 文件
notebook_files = [f for f in os.listdir('.') if f.endswith('.ipynb')]
print(notebook_files)
# 遍历所有 .ipynb 文件
for notebook_file in notebook_files:
    with open(notebook_file, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)

    # 删除每个 cell 的 id 属性
    for cell in nb.cells:
        if 'id' in cell:
            del cell['id']

    # 保存修改后的 notebook 文件
    with open(notebook_file, 'w', encoding='utf-8') as f:
        nbformat.write(nb, f)

print("已成功删除所有 Notebook 文件中的 id 属性。")
