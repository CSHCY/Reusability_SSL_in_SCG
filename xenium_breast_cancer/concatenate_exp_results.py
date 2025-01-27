import pandas as pd
import os

# 定义拼接顺序
order = [
    (42, 'barlow_twins_fine_tune'),
    (476, 'barlow_twins_fine_tune'),
    (761, 'barlow_twins_fine_tune'),
    (3407, 'barlow_twins_fine_tune'),
    (9824, 'barlow_twins_fine_tune'),
    (42, 'barlow_twins_zero_shot'),
    (476, 'barlow_twins_zero_shot'),
    (761, 'barlow_twins_zero_shot'),
    (3407, 'barlow_twins_zero_shot'),
    (9824, 'barlow_twins_zero_shot'),
    (42, 'GP_mask_fine_tune'),
    (476, 'GP_mask_fine_tune'),
    (761, 'GP_mask_fine_tune'),
    (3407, 'GP_mask_fine_tune'),
    (9824, 'GP_mask_fine_tune'),
    (42, 'GP_mask_zero_shot'),
    (476, 'GP_mask_zero_shot'),
    (761, 'GP_mask_zero_shot'),
    (3407, 'GP_mask_zero_shot'),
    (9824, 'GP_mask_zero_shot'),
    (42, 'random_mask_fine_tune'),
    (476, 'random_mask_fine_tune'),
    (761, 'random_mask_fine_tune'),
    (3407, 'random_mask_fine_tune'),
    (9824, 'random_mask_fine_tune'),
    (42, 'random_mask_zero_shot'),
    (476, 'random_mask_zero_shot'),
    (761, 'random_mask_zero_shot'),
    (3407, 'random_mask_zero_shot'),
    (9824, 'random_mask_zero_shot'),
    (42, 'supervised'),
    (476, 'supervised'),
    (761, 'supervised'),
    (3407, 'supervised'),
    (9824, 'supervised'),
    (42, 'PCA'),
    (476, 'PCA'),
    (761, 'PCA'),
    (3407, 'PCA'),
    (9824, 'PCA')
]

# 定义结果文件夹路径
results_folder = './results'

# 创建空的 DataFrame，用于存储所有拼接的数据
combined_df = pd.DataFrame()

# 遍历定义的顺序
for random_seed, method in order:
    # 拼接生成的 CSV 文件名
    csv_filename = f"{results_folder}/Xenium_breast_cancer_sample1_replicate1_{method}_{random_seed}_results.csv"
    
    # 检查文件是否存在
    if os.path.exists(csv_filename):
        # 读取 CSV 文件
        df = pd.read_csv(csv_filename)
        
        # 将 CSV 中的内容添加到合并的 DataFrame 中
        combined_df = pd.concat([combined_df, df], ignore_index=True)
    else:
        print(f"Warning: {csv_filename} not found. Skipping.")

# 将合并的 DataFrame 保存为一个新的 CSV 文件
combined_csv_filename = f"{results_folder}/combined_results.csv"
combined_df.to_csv(combined_csv_filename, index=False)

print(f"All CSV files have been combined and saved to {combined_csv_filename}.")
