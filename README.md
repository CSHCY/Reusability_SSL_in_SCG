# Reusability Report: Evaluating the Transferability of Self-Supervised Learning Models from Single-Cell to Spatial Transcriptomics

This repository contains the code associated with our reusability study, entitled "Evaluating the Transferability of Self-Supervised Learning Models from Single-Cell to Spatial Transcriptomics".

## Overview

This work builds upon the research presented in Richter et al. (2024), "Delineating the effective use of self-supervised learning in single-cell genomics", *Nature Machine Intelligence*. We evaluate the transferability of their pre-trained self-supervised learning (SSL) models (Random Mask, GP Mask, and Barlow Twins) to the domain of spatial transcriptomics. Our study investigates the performance of these models on cell type prediction and spatial clustering tasks, using various spatial transcriptomics datasets generated by different technologies (MERSCOPE, Xenium, and Slide-seqV2).
![Reusability Report Fig1 250125](https://github.com/CSHCY/Reusability_SSL_in_SCG/blob/main/images/Reusability%20Report%20Fig1%20250125.jpg)

## Key Findings

*   Pre-trained SSL models show limited transferability to spatial transcriptomics data for cell type prediction, showcasing a significant domain gap between non-spatial single-cell transcriptomics and spatial transcriptomics.
*   Random Mask embeddings enhance the performance of spatial clustering methods (STAGATE-RM and GraphST-RM).
*   Gene imputation could negatively impact SSL model performance in spatial transcriptomics in our experimental case.
*   Cross-species transfer presents significant challenges for SSL models.


## Getting Started

**Clone the repository:**
```bash
  git clone https://github.com/CSHCY/Reusability_SSL_in_SCG
```
**Create and activate the conda environment:**

```bash
conda create -n ssl-transferability python==3.10
conda activate ssl-transferability
```

Install requirements:

```bash
pip install -r requirements-gpu.txt
```

**Pretrained Models:**

Download the pre-trained models from https://huggingface.co/TillR/sc_pretrained/tree/main/Pretrained%20Models, and deposit the models at "./sc_pretrained/".

**Reproduce our experiments:**

Jupyter notebooks can be used to reproduce the experiments and generate the figures in our paper. Before reproducing our experiments, please first git clone the code from the original study at https://github.com/theislab/ssl_in_scg.

**Original Study**

Richter T, Bahrami M, Xia Y, et al. Delineating the effective use of self-supervised learning in single-cell genomics[J]. Nature Machine Intelligence, 2024: 1-11.

**Original Code**

https://github.com/theislab/ssl_in_scg

**Contact**

For any questions or issues, please contact Chuangyi Han at chuangyihan22@m.fudan.edu.cn.
