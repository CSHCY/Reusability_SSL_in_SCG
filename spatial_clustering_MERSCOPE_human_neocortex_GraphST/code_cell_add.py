import os
import json
import nbformat
import csv

# 遍历当前目录下的所有 .ipynb 文件
for notebook_file in os.listdir('.'):
    if notebook_file.endswith('.ipynb'):
        print(notebook_file)

        # 读取 .ipynb 文件
        try:
            with open(notebook_file, 'r', encoding='utf-8') as f:
                nb = nbformat.read(f, as_version=4)

            # 硬编码当前 Notebook 的文件名
            notebook_name = os.path.basename(notebook_file)

            # 获取实验名称
            experiment_name = os.path.splitext(notebook_name)[0]

            # 定义要添加的代码单元
            code_to_add = f"""
# 保存到当前目录下名为 results 的文件夹中
# 当前 Notebook 文件名和实验名称
notebook_name = "{notebook_name}"
experiment_name = "{experiment_name}"

if not os.path.exists('results'):
    os.makedirs('results')

# 定义 CSV 文件的路径
csv_filename = f"results/{{experiment_name}}_results.csv"

# 保存 Batch, NMI, ARI, 和 experiment_name 到 CSV 文件中
import csv
with open(csv_filename, 'a', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    # 如果文件是新建的，写入表头
    if os.stat(csv_filename).st_size == 0:
        writer.writerow(['Experiment Name', 'Batch', 'NMI', 'ARI'])
    writer.writerow([experiment_name, batch, nmi, ari])
"""
            modified = False

            # 遍历每个 cell
            for cell in nb['cells']:
                if cell['cell_type'] == 'code':
                    cell_content = ''.join(cell['source'])

                    # 检查 cell 是否包含目标代码块
                    if 'nmi_values = []' in cell_content and 'plt.close()' in cell_content:
                        # 确保 cell['source'] 是列表类型
                        if isinstance(cell['source'], str):
                            cell['source'] = [cell['source']]
                        cell['source'].append(code_to_add)
                        modified = True

            # 保存修改后的 .ipynb 文件
            if modified:
                with open(notebook_file, 'w', encoding='utf-8') as f:
                    nbformat.write(nb, f)

        except Exception as e:
            print(f"Error processing {notebook_file}: {e}")

print("All .ipynb files have been processed and modified. Results will be written to CSV files in the 'results' folder.")
