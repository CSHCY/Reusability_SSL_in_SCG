import nbformat
import os
print(os.getcwd())
# 指定包含 .ipynb 文件的目录
notebook_directory = '.'

# 获取指定目录下所有 .ipynb 文件的完整路径
notebook_files = [os.path.join(notebook_directory, f) for f in os.listdir(notebook_directory) if f.endswith('.ipynb')]

print("当前工作目录:", os.getcwd())
print("找到的 .ipynb 文件:", notebook_files)

# 遍历所有 .ipynb 文件
for notebook_file in notebook_files:
    # 读取 .ipynb 文件
    try:
        with open(notebook_file, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        nb.cells = nb.cells[:-1]
        # 硬编码当前 Notebook 的文件名
        notebook_name = os.path.basename(notebook_file)

        # 定义要添加的代码单元
        code_to_add = f"""
import pandas as pd
import os
import re

# 当前 Notebook 文件名
notebook_name = "{notebook_name}"

# 初始化需要打印的值
init_train_loss = train_losses[0] if 'train_losses' in globals() else None
init_val_loss = val_losses[0] if 'val_losses' in globals() else None
converged_epoch = len(train_losses) - patience if 'train_losses' in globals() else None
converged_val_loss = best_val_loss if 'best_val_loss' in globals() else None

# 打印所有所需的指标
print("Metrics Summary:")
if 'train_losses' in globals():
    print(f"init_train_loss\\tinit_val_loss\\tconverged_epoch\\tconverged_val_loss\\tmacro_f1\\tweighted_f1\\tmicor_f1")
    print(f"{{init_train_loss:.3f}}\\t{{init_val_loss:.3f}}\\t{{converged_epoch}}\\t{{converged_val_loss:.3f}}\\t{{macro_f1:.3f}}\\t{{f1:.3f}}\\t{{accuracy:.3f}}")
else:
    print(f"macro_f1\\tweighted_f1\\tmicor_f1")
    print(f"{{macro_f1:.3f}}\\t{{f1:.3f}}\\t{{accuracy:.3f}}")

# 保存结果到 CSV 文件
output_data = {{
    'dataset_split_random_seed': [int(random_seed)],
    'dataset': ['slide_seq_mouse_kidney'],
    'method': [re.search(r'kidney_(.*?)_\\d+', notebook_name).group(1)],
    'init_train_loss': [init_train_loss if init_train_loss is not None else ''],
    'init_val_loss': [init_val_loss if init_val_loss is not None else ''],
    'converged_epoch': [converged_epoch if converged_epoch is not None else ''],
    'converged_val_loss': [converged_val_loss if converged_val_loss is not None else ''],
    'macro_f1': [macro_f1],
    'weighted_f1': [f1],
    'micor_f1': [accuracy]
}}
output_df = pd.DataFrame(output_data)

# 保存到当前目录下名为 results 的文件夹中
if not os.path.exists('results'):
    os.makedirs('results')

csv_filename = f"results/{{os.path.splitext(notebook_name)[0]}}_results.csv"
output_df.to_csv(csv_filename, index=False)
"""

        # 创建一个新的代码单元
        new_cell = nbformat.v4.new_code_cell(code_to_add)

        # 将新的代码单元添加到 notebook 的最后
        nb.cells.append(new_cell)

        # 保存修改后的 notebook 文件
        with open(notebook_file, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)

        print(f"已成功将代码单元添加到 {notebook_file} 的末尾。")

    except FileNotFoundError:
        print(f"未找到文件: {notebook_file}")

print("所有操作完成。")
