import abc
import gc
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np
import lightning.pytorch as pl
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import (
    Bernoulli,
    ContinuousBernoulli,
    Poisson,
)
from scvi.distributions import NegativeBinomial, ZeroInflatedNegativeBinomial
from torchmetrics import ExplainedVariance, MeanSquaredError, MetricCollection
from torchmetrics.classification import MulticlassF1Score
from self_supervision.models.base.base import MLP
from self_supervision.models.contrastive.byol import BYOL
from self_supervision.models.contrastive.bt import (
    BarlowTwins,
    Transform,
    LARS,
    adjust_learning_rate,
)



def _mask_gene_programs_numpy(
    inputs: torch.Tensor, encoded_gene_program: np.ndarray, masking_rate: float
):
    """
    Randomly choose masking_rate percent of the gene programs (rows) to mask.
    Mask all the genes in the inputs tensor that are 1s in the chosen row of encoded_gene_program.
    return a binary mask of the tensor and a fraction of how many genes are set to 0.
    :param inputs: input data
    :param encoded_gene_program: encoded gene programs
    :param masking_rate: rate of gene programs to mask
    :return: mask, frac: mask is a binary mask of the tensor and frac is a fraction of how many genes are set to 0.
    """
    # Randomly choose masking_rate percent of the gene programs to mask
    num_gene_programs = encoded_gene_program.shape[0]
    num_gene_programs_to_mask = int(num_gene_programs * masking_rate)
    gene_programs_to_mask = np.random.permutation(num_gene_programs)[
        :num_gene_programs_to_mask
    ]
    # Mask the input tensor and cast it to numpy on cpu
    mask = np.ones_like(inputs.cpu().numpy())
    for ix in gene_programs_to_mask:
        mask[:, encoded_gene_program[ix, :] == 1] = 0
    return mask, 1 - mask.sum() / mask.size


def _only_activate_gene_program_numpy(
    inputs: torch.Tensor,
    # write that encoded_gene_program is a dict of a tuple of torch.Tensor
    # encoded_gene_program: Dict[Tuple[torch.Tensor, torch.Tensor]],
    encoded_gene_program: Dict,
):
    """
    For each row of the inputs tensor randomly choose one transcription factor (key of encoded_gene_program)
    The first element of encoded_gene_program[key] is a vector (torch.Tensor) of indices of genes in the gene program.
    The input mask should correspond to that mask, i.e., the mask is 1 where the genes are in the gene program.
    The second element of encoded_gene_program[key] is a vector (torch.Tensor) of index of the corresponding gene program.
    The output mask should be 1 that vector is 1.
    :param inputs: input data
    :param encoded_gene_program: encoded gene programs
    :return: (input_mask, output_mask): input_mask is a binary mask of the tensor and output_mask is a binary mask of the tensor.
    """
    # Randomly choose one transcription factor (key of encoded_gene_program) per row of the inputs tensor
    num_gene_programs = len(encoded_gene_program)
    gene_programs_to_activate = np.random.permutation(num_gene_programs)[
        : inputs.shape[0]
    ]
    # Mask the input tensor and cast it to numpy on cpu
    input_mask = np.zeros_like(inputs.cpu().numpy())
    output_mask = np.zeros_like(inputs.cpu().numpy())
    for ix, key in enumerate(gene_programs_to_activate):
        input_mask[ix, encoded_gene_program[key][0]] = 1
        output_mask[ix, encoded_gene_program[key][1]] = 1
    return input_mask, output_mask


def _mask_single_gene_programs(
    inputs: torch.Tensor,
    encoded_gene_program: np.ndarray,
):
    """
    Randomly choose 1 gene program, mask everything apart from that gene program both in the input and output.
    """
    # Randomly choose 1 gene program
    num_gene_programs = encoded_gene_program.shape[0]
    gene_program_to_mask = np.random.permutation(num_gene_programs)[:1]
    # Mask the input tensor and cast it to numpy on cpu
    input_mask = np.zeros_like(inputs.cpu().numpy())
    output_mask = np.zeros_like(inputs.cpu().numpy())
    input_mask[:, encoded_gene_program[gene_program_to_mask, :] == 1] = 1
    output_mask[:, encoded_gene_program[gene_program_to_mask, :] == 1] = 1
    return input_mask, output_mask


class BaseAutoEncoder(pl.LightningModule, abc.ABC):
    """
    Base class for AutoEncoder models in PyTorch Lightning.

    Args:
        gene_dim (int): Dimension of the gene.
        train_set_size (int): Size of the training set.
        val_set_size (int): Size of the validation set.
        batch_size (int): Batch size.
        reconst_loss (str, optional): Reconstruction loss function. Defaults to 'mse'.
        learning_rate (float, optional): Learning rate. Defaults to 0.005.
        weight_decay (float, optional): Weight decay. Defaults to 0.1.
        optimizer (Callable[..., torch.optim.Optimizer], optional): Optimizer class. Defaults to torch.optim.AdamW.
        lr_scheduler (Callable, optional): Learning rate scheduler. Defaults to None.
        lr_scheduler_kwargs (Dict, optional): Additional arguments for the learning rate scheduler. Defaults to None.
        gc_frequency (int, optional): Frequency of garbage collection. Defaults to 1.
        automatic_optimization (bool, optional): Whether to use automatic optimization. Defaults to True.
        supervised_subset (Optional[int], optional): Subset size for supervised training. Defaults to None.
    """

    autoencoder: nn.Module  # autoencoder mapping von gene_dim to gene_dim

    def __init__(
        self,
        gene_dim: int,
        train_set_size: int,
        val_set_size: int,
        batch_size: int,
        reconst_loss: str = "mse",
        learning_rate: float = 0.005,
        weight_decay: float = 0.1,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,
        lr_scheduler_kwargs: Dict = None,
        gc_frequency: int = 1,
        automatic_optimization: bool = True,
        supervised_subset: Optional[int] = None,
        donor_subset: Optional[List[int]] = None,
    ):
        super(BaseAutoEncoder, self).__init__()

        self.automatic_optimization = automatic_optimization

        self.gene_dim = gene_dim
        self.train_set_size = train_set_size
        self.val_set_size = val_set_size
        self.batch_size = batch_size
        self.gc_freq = gc_frequency
        self.lr = learning_rate
        self.weight_decay = weight_decay
        self.optim = optimizer
        self.reconst_loss = reconst_loss
        self.lr_scheduler = lr_scheduler
        self.lr_scheduler_kwargs = lr_scheduler_kwargs
        self.supervised_subset = supervised_subset
        self.donor_subset = donor_subset

        metrics = MetricCollection(
            {
                "explained_var_weighted": ExplainedVariance(
                    multioutput="variance_weighted"
                ),
                "explained_var_uniform": ExplainedVariance(
                    multioutput="uniform_average"
                ),
                "mse": MeanSquaredError(),
            }
        )

        self.train_metrics = metrics.clone(prefix="train_")
        self.val_metrics = metrics.clone(prefix="val_")
        self.test_metrics = metrics.clone(prefix="test_")

    def _calc_reconstruction_loss(
        self, preds: torch.Tensor, targets: torch.Tensor, reduction: str = "mean"
    ):
        """
        Calculate the reconstruction loss.

        Args:
            preds (torch.Tensor): Predicted values.
            targets (torch.Tensor): Target values.
            reduction (str, optional): Reduction method. Defaults to 'mean'.

        Returns:
            torch.Tensor: Reconstruction loss.
        """
        if self.reconst_loss == "continuous_bernoulli":
            loss = -ContinuousBernoulli(probs=preds).log_prob(targets)
            if reduction == "mean":
                loss = loss.mean()
            elif reduction == "sum":
                loss = loss.sum()
        elif self.reconst_loss == "bce":
            loss = F.binary_cross_entropy(preds, targets, reduction=reduction)
        elif self.reconst_loss == "mae":
            loss = F.l1_loss(preds, targets, reduction=reduction)
        else:
            loss = F.mse_loss(preds, targets, reduction=reduction)
        return loss

    @abc.abstractmethod
    def _step(self, batch):
        """
        Calculate predictions (int64 tensor) and loss.

        Args:
            batch: Input batch.

        Returns:
            tuple: Tuple containing predictions and loss.
        """
        pass

    def on_after_batch_transfer(self, batch, dataloader_idx):
        """
        Perform operations on the batch after it has been transferred to the device.

        Args:
            batch: Input batch.
            dataloader_idx: Index of the dataloader.

        Returns:
            batch: Processed batch.
        """
        if isinstance(batch, dict):  # Case for MultiomicsDataloader
            return batch
        else:
            return batch[0]

    def forward(self, batch):
        """
        Forward pass of the autoencoder.

        Args:
            batch: Input batch.

        Returns:
            tuple: Tuple containing the latent representation and the reconstructed output.
        """
        x_in = batch["X"]
        x_latent = self.encoder(x_in)
        x_reconst = self.decoder(x_latent)
        return x_latent, x_reconst

    def on_train_epoch_end(self) -> None:
        """
        Perform operations at the end of each training epoch.
        """
        gc.collect()

    def on_validation_epoch_end(self) -> None:
        """
        Perform operations at the end of each validation epoch.
        """
        gc.collect()

    def configure_optimizers(self):
        """
        Configure the optimizer and learning rate scheduler.

        Returns:
            dict: Configuration for the optimizer and learning rate scheduler.
        """
        optimizer_config = {
            "optimizer": self.optim(
                self.parameters(), lr=self.lr, weight_decay=self.weight_decay
            )
        }
        if self.lr_scheduler is not None:
            lr_scheduler_kwargs = (
                {} if self.lr_scheduler_kwargs is None else self.lr_scheduler_kwargs
            )
            interval = lr_scheduler_kwargs.pop("interval", "epoch")
            monitor = lr_scheduler_kwargs.pop("monitor", "val_loss_epoch")
            frequency = lr_scheduler_kwargs.pop("frequency", 1)
            scheduler = self.lr_scheduler(
                optimizer_config["optimizer"], **lr_scheduler_kwargs
            )
            optimizer_config["lr_scheduler"] = {
                "scheduler": scheduler,
                "interval": interval,
                "monitor": monitor,
                "frequency": frequency,
            }

        return optimizer_config


class BaseClassifier(pl.LightningModule, abc.ABC):
    """
    Base classifier module for a PyTorch Lightning model.

    Args:
        gene_dim (int): Dimension of the gene feature.
        type_dim (int): Dimension of the cell type.
        class_weights (np.ndarray): Array of class weights.
        child_matrix (np.ndarray): Matrix representing the child relationship between cell types.
        train_set_size (int): Size of the training set.
        val_set_size (int): Size of the validation set.
        batch_size (int): Batch size.
        supervised_subset (Optional[int], optional): Subset of the data to use for supervised training. Defaults to None.
        learning_rate (float, optional): Learning rate. Defaults to 0.005.
        weight_decay (float, optional): Weight decay. Defaults to 0.1.
        optimizer (Callable[..., torch.optim.Optimizer], optional): Optimizer function. Defaults to torch.optim.AdamW.
        lr_scheduler (Callable, optional): Learning rate scheduler. Defaults to None.
        lr_scheduler_kwargs (Dict, optional): Additional arguments for the learning rate scheduler. Defaults to None.
        gc_frequency (int, optional): Frequency of garbage collection. Defaults to 1.
    """

    classifier: Callable  # classifier mapping von gene_dim to type_dim - outputs logits

    def __init__(
        self,
        gene_dim: int,
        type_dim: int,
        class_weights: np.ndarray,
        child_matrix: np.ndarray,
        train_set_size: int,
        val_set_size: int,
        batch_size: int,
        supervised_subset: Optional[int] = None,
        learning_rate: float = 0.005,
        weight_decay: float = 0.1,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,
        lr_scheduler_kwargs: Dict = None,
        gc_frequency: int = 1,
    ):
        super(BaseClassifier, self).__init__()

        self.gene_dim = gene_dim
        self.type_dim = type_dim
        self.train_set_size = train_set_size
        self.val_set_size = val_set_size
        self.batch_size = batch_size
        self.gc_freq = gc_frequency
        self.supervised_subset = supervised_subset

        self.lr = learning_rate
        self.weight_decay = weight_decay
        self.optim = optimizer
        self.lr_scheduler = lr_scheduler
        self.lr_scheduler_kwargs = lr_scheduler_kwargs

        metrics = MetricCollection(
            {
                "f1_micro": MulticlassF1Score(num_classes=type_dim, average="micro"),
                "f1_macro": MulticlassF1Score(num_classes=type_dim, average="macro"),
            }
        )
        self.train_metrics = metrics.clone(prefix="train_")
        self.val_metrics = metrics.clone(prefix="val_")
        self.test_metrics = metrics.clone(prefix="test_")

        self.register_buffer("class_weights", torch.tensor(class_weights.astype("f4")))
        self.register_buffer("child_lookup", torch.tensor(child_matrix.astype("i8")))

    @abc.abstractmethod
    def _step(self, batch, training=True) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Abstract method for performing a step in the training, validation, or testing process.

        Args:
            batch: Input batch data.
            training (bool, optional): Flag indicating whether the model is in training mode. Defaults to True.

        Returns:
            Tuple[torch.Tensor, torch.Tensor]: Tuple containing the predictions and the loss.
        """
        pass

    def hierarchy_correct(self, preds, targets) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Corrects the predictions and targets based on the hierarchy of cell types.

        Args:
            preds (torch.Tensor): Predicted cell types.
            targets (torch.Tensor): Target cell types.

        Returns:
            Tuple[torch.Tensor, torch.Tensor]: Tuple containing the corrected predictions and targets.
        """
        pred_is_child_node_or_node = (
            torch.sum(
                self.child_lookup[targets, :] * F.one_hot(preds, self.type_dim), dim=1
            )
            > 0
        )

        return (
            torch.where(pred_is_child_node_or_node, targets, preds),  # corrected preds
            torch.where(
                pred_is_child_node_or_node, preds, targets
            ),  # corrected targets
        )

    def on_after_batch_transfer(self, batch, dataloader_idx):
        """
        Callback function called after transferring the batch to the device.

        Args:
            batch: Input batch data.
            dataloader_idx: Index of the dataloader.

        Returns:
            batch: Transformed batch data.
        """
        with torch.no_grad():
            batch = batch[0]
            batch["cell_type"] = torch.squeeze(batch["cell_type"])

        return batch

    def forward(self, x: torch.Tensor):
        """
        Forward pass of the model.

        Args:
            x (torch.Tensor): Input tensor.

        Returns:
            torch.Tensor: Output tensor.
        """
        # If x is a tuple, which can happen in some testing due to lightning, then we need to extract the tensor
        if isinstance(x, dict):
            x = x["X"]
        if isinstance(x, tuple):
            x = x[0]["X"]

        return self.classifier(x)

    def training_step(self, batch, batch_idx):
        """
        Training step of the model.

        Args:
            batch: Input batch data.
            batch_idx: Index of the batch.

        Returns:
            loss: Training loss.
        """
        if self.supervised_subset is not None:
            # Create a mask vector to filter the batch based on the supervised subset and return none if supervised subset is not in the batch
            mask = torch.tensor([id in self.supervised_subset for id in batch["dataset_id"]])
            if not any(mask):
                return None
            # Filter the batch based on the mask
            batch = {key: value[mask] for key, value in batch.items()}

        preds, loss = self._step(batch, training=True)
        self.log("train_loss", loss)
        f1_macro = self.train_metrics["f1_macro"](preds, batch["cell_type"])
        f1_micro = self.train_metrics["f1_micro"](preds, batch["cell_type"])
        self.log("train_f1_macro_step", f1_macro)
        self.log("train_f1_micro_step", f1_micro)

        if batch_idx % self.gc_freq == 0:
            gc.collect()

        return loss

    def validation_step(self, batch, batch_idx):
        """
        Validation step of the model.

        Args:
            batch: Input batch data.
            batch_idx: Index of the batch.
        """
        if self.supervised_subset is not None:
            # Create a mask vector to filter the batch based on the supervised subset and return none if supervised subset is not in the batch
            mask = torch.tensor([id in self.supervised_subset for id in batch["dataset_id"]])
            if not any(mask):
                return None
            # Filter the batch based on the mask
            batch = {key: value[mask] for key, value in batch.items()}
        preds, loss = self._step(batch, training=False)
        self.log("val_loss", loss)
        self.val_metrics["f1_macro"].update(preds, batch["cell_type"])
        self.val_metrics["f1_micro"].update(preds, batch["cell_type"])
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def test_step(self, batch, batch_idx):
        """
        Test step of the model.

        Args:
            batch: Input batch data.
            batch_idx: Index of the batch.
        """
        if self.supervised_subset is not None:
            # Create a mask vector to filter the batch based on the supervised subset and return none if supervised subset is not in the batch
            mask = torch.tensor([id in self.supervised_subset for id in batch["dataset_id"]])
            if not any(mask):
                return None
            # Filter the batch based on the mask
            batch = {key: value[mask] for key, value in batch.items()}
        preds, loss = self._step(batch, training=False)
        self.log("test_loss", loss)
        self.test_metrics["f1_macro"].update(preds, batch["cell_type"])
        self.test_metrics["f1_micro"].update(preds, batch["cell_type"])
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def on_train_epoch_end(self) -> None:
        self.log("train_f1_macro_epoch", self.train_metrics["f1_macro"].compute())
        self.train_metrics["f1_macro"].reset()
        self.log("train_f1_micro_epoch", self.train_metrics["f1_micro"].compute())
        self.train_metrics["f1_micro"].reset()
        gc.collect()

    def on_validation_epoch_end(self) -> None:
        f1_macro = self.val_metrics["f1_macro"].compute()
        self.log("val_f1_macro", f1_macro)
        self.log("hp_metric", f1_macro)
        self.val_metrics["f1_macro"].reset()
        self.log("val_f1_micro", self.val_metrics["f1_micro"].compute())
        self.val_metrics["f1_micro"].reset()
        gc.collect()

    def on_test_epoch_end(self) -> None:
        self.log("test_f1_macro", self.test_metrics["f1_macro"].compute())
        self.test_metrics["f1_macro"].reset()
        self.log("test_f1_micro", self.test_metrics["f1_micro"].compute())
        self.test_metrics["f1_micro"].reset()
        gc.collect()

    def configure_optimizers(self):
        optimizer_config = {
            "optimizer": self.optim(
                self.parameters(), lr=self.lr, weight_decay=self.weight_decay
            )
        }
        if self.lr_scheduler is not None:
            lr_scheduler_kwargs = (
                {} if self.lr_scheduler_kwargs is None else self.lr_scheduler_kwargs
            )
            interval = lr_scheduler_kwargs.pop("interval", "epoch")
            monitor = lr_scheduler_kwargs.pop("monitor", "val_loss_epoch")
            frequency = lr_scheduler_kwargs.pop("frequency", 1)
            scheduler = self.lr_scheduler(
                optimizer_config["optimizer"], **lr_scheduler_kwargs
            )
            optimizer_config["lr_scheduler"] = {
                "scheduler": scheduler,
                "interval": interval,
                "monitor": monitor,
                "frequency": frequency,
            }

        return optimizer_config


class MLPAutoEncoder(BaseAutoEncoder):
    def __init__(
        self,
        # fixed params
        gene_dim: int,
        units_encoder: List[int],
        units_decoder: List[int],
        # params from datamodule
        train_set_size: int = None,
        val_set_size: int = None,
        batch_size: int = None,
        # model specific params
        supervised_subset: Optional[int] = None,
        donor_subset: Optional[List[int]] = None,
        reconstruction_loss: str = "mse",
        learning_rate: float = 0.005,
        weight_decay: float = 0.1,
        dropout: float = 0.1,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,
        lr_scheduler_kwargs: Dict = None,
        output_activation: Callable[[], torch.nn.Module] = nn.Sigmoid,
        activation: Callable[[], torch.nn.Module] = nn.SELU,
        # params for masking
        masking_rate: Optional[float] = None,
        masking_strategy: Optional[str] = None,  # 'random', 'gene_program'
        encoded_gene_program: Optional[Dict] = None,
    ):
        # check input
        assert 0.0 <= dropout <= 1.0
        assert reconstruction_loss in ["mse", "mae", "continuous_bernoulli", "bce"]
        if reconstruction_loss in ["continuous_bernoulli", "bce"]:
            assert output_activation == nn.Sigmoid

        self.train_set_size = train_set_size
        self.val_set_size = val_set_size
        self.batch_size = batch_size
        self.supervised_subset = supervised_subset
        self.donor_subset = donor_subset

        super(MLPAutoEncoder, self).__init__(
            gene_dim=gene_dim,
            train_set_size=train_set_size,
            val_set_size=val_set_size,
            batch_size=batch_size,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            optimizer=optimizer,
            lr_scheduler=lr_scheduler,
            lr_scheduler_kwargs=lr_scheduler_kwargs,
            supervised_subset=supervised_subset,
            donor_subset=donor_subset,
        )

        self.encoder = MLP(
            in_channels=gene_dim,
            hidden_channels=units_encoder,
            activation_layer=activation,
            inplace=False,
            dropout=dropout,
        )
        # Define decoder network
        self.decoder = nn.Sequential(
            MLP(
                in_channels=units_encoder[-1],
                hidden_channels=units_decoder + [gene_dim],
                # norm_layer=_get_norm_layer(batch_norm=batch_norm, layer_norm=layer_norm),
                activation_layer=activation,
                inplace=False,
                dropout=dropout,
            ),
            output_activation(),
        )

        self.predict_bottleneck = False

        metrics = MetricCollection(
            {
                "explained_var_weighted": ExplainedVariance(
                    multioutput="variance_weighted"
                ),
                "explained_var_uniform": ExplainedVariance(
                    multioutput="uniform_average"
                ),
                "mse": MeanSquaredError(),
            }
        )

        self.train_metrics = metrics.clone(prefix="train_")
        self.val_metrics = metrics.clone(prefix="val_")
        self.test_metrics = metrics.clone(prefix="test_")

        # masking
        self.masking_rate = masking_rate
        self.masking_strategy = masking_strategy
        self.encoded_gene_program = encoded_gene_program


    def _step(self, batch, training=True):
        targets = batch["X"]
        inputs = batch["X"]

        if self.masking_rate and self.masking_strategy == "random":
            mask = (
                Bernoulli(probs=1.0 - self.masking_rate)
                .sample(targets.size())
                .to(targets.device)
            )
            # upscale inputs to compensate for masking and convert to same device
            masked_inputs = 1.0 / (1.0 - self.masking_rate) * (inputs * mask)
            x_latent, x_reconst = self(masked_inputs)
            # calculate masked loss on masked part only
            inv_mask = torch.abs(torch.ones(mask.size()).to(targets.device) - mask)
            loss = (
                inv_mask
                * self._calc_reconstruction_loss(x_reconst, targets, reduction="none")
            ).mean()

        elif self.masking_rate and self.masking_strategy == "gene_program":
            with torch.no_grad():
                # self.encoded gene program is a numpy array of encoded gene programs
                mask, frac = _mask_gene_programs_numpy(
                    inputs, self.encoded_gene_program, self.masking_rate
                )
                mask = torch.tensor(mask).to(inputs.device)
                # log the fraction of genes masked
                self.log("frac_genes_masked", frac)
                # mask, frac = self.mask_gene_programs(inputs, self.gene_program_dict, self.masking_rate)
            # upscale inputs to compensate for masking
            masked_inputs = 1.0 / (1.0 - frac) * (inputs * mask.to(inputs.device))
            x_latent, x_reconst = self(masked_inputs)
            # calculate masked loss
            inv_mask = torch.abs(torch.ones(mask.size()).to(targets.device) - mask)
            loss = (
                inv_mask.to(inputs.device)
                * self._calc_reconstruction_loss(x_reconst, targets, reduction="none")
            ).mean()

        elif self.masking_rate and self.masking_strategy == "single_gene_program":
            with torch.no_grad():
                # self.encoded gene program is a numpy array of encoded gene programs
                input_mask, output_mask = _mask_single_gene_programs(
                    inputs, self.encoded_gene_program
                )
                # log the fraction of genes masked
                self.log("frac_genes_masked", frac)
            # upscale inputs to compensate for masking
            masked_inputs = (
                1.0
                / (1.0 - frac)
                * (inputs * torch.tensor(input_mask).to(inputs.device))
            )
            x_latent, x_reconst = self(masked_inputs)
            # calculate masked loss only on the output_mask part of the reconstruction
            inv_output_mask = torch.abs(
                torch.ones(output_mask.size()).to(targets.device) - output_mask
            )
            loss = (
                torch.tensor(inv_output_mask).to(inputs.device)
                * self._calc_reconstruction_loss(x_reconst, targets, reduction="none")
            ).mean()

        elif self.masking_rate and self.masking_strategy == "gp_to_tf":
            with torch.no_grad():
                # self.encoded gene program is a Dict of encoded gene programs and the corresponding tf indices
                input_mask, output_mask = _only_activate_gene_program_numpy(
                    inputs, self.encoded_gene_program
                )
                # log the fraction of genes masked
                self.log("frac_genes_masked", frac)
            # upscale inputs to compensate for masking
            masked_inputs = (
                1.0
                / (1.0 - frac)
                * (inputs * torch.tensor(input_mask).to(inputs.device))
            )
            x_latent, x_reconst = self(masked_inputs)
            # calculate masked loss only on the output_mask part of the reconstruction
            inv_output_mask = torch.abs(
                torch.ones(output_mask.size()).to(targets.device) - output_mask
            )
            loss = (
                torch.tensor(inv_output_mask).to(inputs.device)
                * self._calc_reconstruction_loss(x_reconst, targets, reduction="none")
            ).mean()

        # raise error if masking rate is not none but masking strategy is not implemented
        elif self.masking_rate and self.masking_strategy not in [
            "random",
            "gene_program",
        ]:
            raise ValueError(
                f"Masking strategy {self.masking_strategy} not implemented."
            )

        # raise error if masking strategy is not none but masking rate is 0.0
        elif self.masking_strategy and self.masking_rate == 0.0:
            raise ValueError(
                f"Masking rate is 0 ({self.masking_rate}),"
                f" but masking strategy {self.masking_strategy} is not None."
            )

        else:
            x_latent, x_reconst = self(inputs.to(targets.device))
            loss = self._calc_reconstruction_loss(x_reconst, targets, reduction="mean")

        return x_reconst, loss

    def predict_embedding(self, batch):
        return self.encoder(batch["X"])

    def forward(self, x_in):
        x_latent = self.encoder(x_in)
        x_reconst = self.decoder(x_latent)
        return x_latent, x_reconst

    def training_step(self, batch, batch_idx):
        batch = self.filter_batch(batch)
        if batch is None:
            return None
        x_reconst, loss = self._step(batch)
        self.log_dict(
            self.train_metrics(x_reconst, batch["X"]), on_epoch=True, on_step=True
        )
        self.log("train_loss", loss, on_epoch=True, on_step=True)
        self.log("train_loss_epoch", loss, on_epoch=True, on_step=True)
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        # Log the fraction of genes masked
        return loss

    def validation_step(self, batch, batch_idx):
        batch = self.filter_batch(batch)
        x_reconst, loss = self._step(batch, training=False)
        self.log_dict(self.val_metrics(x_reconst, batch["X"]))
        self.log("val_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def test_step(self, batch, batch_idx):
        batch = self.filter_batch(batch)
        x_reconst, loss = self._step(batch, training=False)
        metrics = self.test_metrics(x_reconst, batch["X"])
        self.log_dict(metrics)
        self.log("test_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return metrics
    
    def filter_batch(self, batch):
        if self.supervised_subset is not None:
            mask = batch["dataset_id"] == self.supervised_subset
            if not mask:
                return None # Skip the batch if no items match the condition

            # Filter the batch based on the mask
            batch = {key: value[mask] for key, value in batch.items()}
        # Donor subset only in train mode
        if self.donor_subset is not None and self.training:

            # Ensure donor IDs are on CPU for membership checking
            donor_ids = batch["donor_id"].cpu().numpy()

            mask = np.isin(donor_ids, list(self.donor_subset))

            # continue if mask contains no True values
            if not mask.any():
                print('No items in batch match the donor subset condition')
                return None
            # Filter the batch based on the mask
            batch = {key: value[mask] for key, value in batch.items()}
        return batch


    def predict_cell_types(self, x: torch.Tensor):
        return F.softmax(self(x)[0], dim=1)

    def predict_step(
        self, batch, batch_idx, dataloader_idx=None, predict_embedding=False
    ):
        if batch_idx % self.gc_freq == 0:
            gc.collect()

        # Apply dataset_id filtering only if supervised_subset is set
        if self.supervised_subset is not None:
            mask = batch["dataset_id"] == self.supervised_subset
            if not mask:
                return None  # Skip the batch if no items match the condition

            # Filter the batch based on the mask
            batch = {key: value[mask] for key, value in batch.items()}

            if predict_embedding:
                return self.encoder(batch["X"]).detach()
            else:
                preds_corrected, loss = self._step(batch, training=False)
                return preds_corrected[mask], batch["cell_type"][mask]

        else:
            if predict_embedding:
                return self.encoder(batch["X"]).detach()
            else:
                x_reconst, loss = self._step(batch, training=False)
                return x_reconst, batch["X"]

    def get_input(self, batch):
        return batch["X"]


class MLPNegBin(BaseAutoEncoder):
    """
    Multi-Layer Perceptron (MLP) Autoencoder with Negative Binomial (NegBin) loss.

    Args:
        gene_dim (int): Dimensionality of the gene input.
        units_encoder (List[int]): List of integers specifying the number of hidden units in each encoder layer.
        units_decoder (List[int]): List of integers specifying the number of hidden units in each decoder layer.
        train_set_size (int): Size of the training set.
        val_set_size (int): Size of the validation set.
        batch_size (int): Batch size.
        supervised_subset (Optional[int]): Subset of the data to use for supervised training. Default is None.
        learning_rate (float): Learning rate for the optimizer. Default is 0.005.
        weight_decay (float): Weight decay for the optimizer. Default is 0.1.
        dropout (float): Dropout rate. Default is 0.1.
        optimizer (Callable[..., torch.optim.Optimizer]): Optimizer class. Default is torch.optim.AdamW.
        lr_scheduler (Callable): Learning rate scheduler. Default is None.
        lr_scheduler_kwargs (Dict): Additional keyword arguments for the learning rate scheduler. Default is None.
        activation (Callable[[], torch.nn.Module]): Activation function. Default is nn.SELU.
        masking_rate (Optional[float]): Rate of masking for input data. Default is None.
        masking_strategy (Optional[str]): Masking strategy for input data. Default is None.
        encoded_gene_program (Optional[Dict]): Encoded gene program. Default is None.

    Raises:
        NotImplementedError: If masking is not implemented for MLPNegBin.

    Attributes:
        encoder (MLP): Encoder module.
        decoder (nn.Sequential): Decoder module.
        masking_rate (Optional[float]): Rate of masking for input data.
        masking_strategy (Optional[str]): Masking strategy for input data.
        encoded_gene_program (Optional[Dict]): Encoded gene program.
    """

    def __init__(
        self,
        gene_dim: int,
        units_encoder: List[int],
        units_decoder: List[int],
        train_set_size: int,
        val_set_size: int,
        batch_size: int,
        supervised_subset: Optional[int] = None,
        gene_likelihood: str = "nb",  # 'zinb', 'nb', 'poisson'
        learning_rate: float = 0.005,
        weight_decay: float = 0.1,
        dropout: float = 0.1,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,
        lr_scheduler_kwargs: Dict = None,
        activation: Callable[[], torch.nn.Module] = nn.SELU,
        # params for masking
        masking_rate: Optional[float] = None,
        masking_strategy: Optional[str] = None,  # 'random', 'gene_program'
        encoded_gene_program: Optional[Dict] = None,
    ):
        super(MLPNegBin, self).__init__(
            gene_dim=gene_dim,
            train_set_size=train_set_size,
            val_set_size=val_set_size,
            batch_size=batch_size,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            optimizer=optimizer,
            lr_scheduler=lr_scheduler,
            lr_scheduler_kwargs=lr_scheduler_kwargs,
            supervised_subset=supervised_subset,
        )

        self.masking_rate = masking_rate
        self.masking_strategy = masking_strategy
        self.encoded_gene_program = encoded_gene_program
        self.gene_likelihood = gene_likelihood
        self.gene_dim = gene_dim

        self.encoder = MLP(
            in_channels=gene_dim,
            hidden_channels=units_encoder,
            activation_layer=activation,
            inplace=False,
            dropout=dropout,
        )

        # Decoder for gene counts
        output_dim = self._get_decoder_output_dim()
        self.decoder = nn.Sequential(
            MLP(
                in_channels=units_encoder[-1],
                hidden_channels=units_decoder + [output_dim],
                activation_layer=activation,
                final_activation=torch.nn.Softplus
                if self.gene_likelihood in ["nb", "zinb"]
                else None,
                inplace=False,
                dropout=dropout,
            )
        )

        # Dispersion parameters
        if gene_likelihood in ["nb", "zinb"]:
            self.px_r = nn.Parameter(torch.randn(self.gene_dim))

        metrics = MetricCollection(
            {
                "explained_var_weighted": ExplainedVariance(
                    multioutput="variance_weighted"
                ),
                "explained_var_uniform": ExplainedVariance(
                    multioutput="uniform_average"
                ),
                "mse": MeanSquaredError(),
            }
        )

        self.train_metrics = metrics.clone(prefix="train_")
        self.val_metrics = metrics.clone(prefix="val_")
        self.test_metrics = metrics.clone(prefix="test_")

        self.masking_rate = masking_rate
        self.masking_strategy = masking_strategy
        self.encoded_gene_program = encoded_gene_program

    def _get_decoder_output_dim(self):
        if self.gene_likelihood == "zinb":
            # Mean, dispersion, dropout logits
            return 3 * self.gene_dim
        elif self.gene_likelihood == "nb":
            # Mean, dispersion
            return 2 * self.gene_dim
        elif self.gene_likelihood == "poisson":
            # Mean only
            return self.gene_dim
        else:
            raise ValueError(f"Invalid gene_likelihood: {self.gene_likelihood}")


    def forward(self, x_in):
        """
        Forward pass of the MLPNegBin model.

        Args:
            x_in (torch.Tensor): Input tensor.

        Returns:
            Tuple[torch.Tensor, torch.Tensor, torch.Tensor]: Tuple containing the latent representation, mean, and inverse dispersion.
        """
        x_latent = self.encoder(x_in)
        output = self.decoder(x_latent)

        if self.gene_likelihood in ["nb", "zinb"]:
            theta = self.px_r.exp()

        # Extract parameters for gene expression likelihood distribution
        if self.gene_likelihood == "zinb":
            mu = output[:, : self.gene_dim]
            pi = output[:, 2 * self.gene_dim :]
            return x_latent, mu, theta, pi
        elif self.gene_likelihood == "nb":
            mu = output[:, : self.gene_dim]
            return x_latent, mu, theta
        elif self.gene_likelihood == "poisson":
            mu = output
            return x_latent, mu

    def _calc_reconstruction_loss(self, x, output, reduction="mean"):
        """
        Calculates the reconstruction loss for the autoencoder.

        Args:
            x (torch.Tensor): The input data.
            output (tuple): The output of the autoencoder.
            reduction (str, optional): Reduction method. Defaults to 'mean'.

        Returns:
            torch.Tensor: The reconstruction loss.
        """
        if self.gene_likelihood == "zinb":
            mu, theta, pi = output
            px = ZeroInflatedNegativeBinomial(mu=mu, theta=theta, zi_logits=pi)
        elif self.gene_likelihood == "nb":
            mu, theta = output
            px = NegativeBinomial(mu=mu, theta=theta)
        elif self.gene_likelihood == "poisson":
            mu = output
            px = Poisson(mu)
        if reduction == "mean":
            return -px.log_prob(x).sum(-1).mean()
        elif reduction == "none":
            return -px.log_prob(x)

    def _calc_reconstruction(self, output):
        """
        Calculates the reconstructed transcriptome from the output of the autoencoder.

        Args:
            output (tuple): The output of the autoencoder.

        Returns:
            torch.Tensor: The reconstructed transcriptome.
        """
        if self.gene_likelihood == "zinb":
            mu, theta, pi = output
            px = ZeroInflatedNegativeBinomial(mu=mu, theta=theta, zi_logits=pi)
        elif self.gene_likelihood == "nb":
            mu, theta = output
            px = NegativeBinomial(mu=mu, theta=theta)
        elif self.gene_likelihood == "poisson":
            mu = output
            px = Poisson(mu)
        return px.mean

    def _step(self, batch, training=True):
        """
        Perform a single training/validation step.

        Args:
            batch (Dict[str, torch.Tensor]): Batch of input data.
            training (bool): Flag indicating whether the model is in training mode. Default is True.

        Returns:
            Tuple[torch.Tensor, torch.Tensor]: Tuple containing the latent representation and loss.
        """
        targets = batch["X"]
        inputs = batch["X"]

        if self.masking_rate and self.masking_strategy == "random":
            mask = (
                Bernoulli(probs=1.0 - self.masking_rate)
                .sample(targets.size())
                .to(targets.device)
            )
            # upscale inputs to compensate for masking and convert to same device
            masked_inputs = 1.0 / (1.0 - self.masking_rate) * (inputs * mask)
            # calculate masked loss on masked part only
            inv_mask = torch.abs(torch.ones(mask.size()).to(targets.device) - mask)

            if self.gene_likelihood == "zinb":
                x_latent, mu, theta, pi = self(masked_inputs)
                loss = (
                    (
                        inv_mask
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta, pi), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta, pi))
            elif self.gene_likelihood == "nb":
                x_latent, mu, theta = self(masked_inputs)
                loss = (
                    (
                        inv_mask
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta))
            elif self.gene_likelihood == "poisson":
                x_latent, mu = self(masked_inputs)
                loss = (
                    (
                        inv_mask
                        * self._calc_reconstruction_loss(targets, mu, reduction="none")
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction(mu)

        elif self.masking_rate and self.masking_strategy == "gene_program":
            with torch.no_grad():
                # self.encoded gene program is a numpy array of encoded gene programs
                mask, frac = _mask_gene_programs_numpy(
                    inputs, self.encoded_gene_program, self.masking_rate
                )
                # log the fraction of genes masked
                self.log("frac_genes_masked", frac)
            # upscale inputs to compensate for masking
            masked_inputs = (
                1.0 / (1.0 - frac) * (inputs * torch.tensor(mask).to(inputs.device))
            )
            # calculate masked loss
            inv_mask = torch.abs(torch.ones(mask.size()).to(targets.device) - mask)
            if self.gene_likelihood == "zinb":
                x_latent, mu, theta, pi = self(masked_inputs)
                loss = (
                    (
                        inv_mask.to(inputs.device)
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta, pi), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta, pi))
            elif self.gene_likelihood == "nb":
                x_latent, mu, theta = self(masked_inputs)
                loss = (
                    (
                        inv_mask.to(inputs.device)
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta))
            elif self.gene_likelihood == "poisson":
                x_latent, mu = self(masked_inputs)
                loss = (
                    (
                        inv_mask.to(inputs.device)
                        * self._calc_reconstruction_loss(targets, mu, reduction="none")
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction(mu)

        elif self.masking_rate and self.masking_strategy == "single_gene_program":
            with torch.no_grad():
                # self.encoded gene program is a numpy array of encoded gene programs
                input_mask, output_mask = _mask_single_gene_programs(
                    inputs, self.encoded_gene_program
                )
                # log the fraction of genes masked
                self.log("frac_genes_masked", frac)
            # upscale inputs to compensate for masking
            masked_inputs = (
                1.0
                / (1.0 - frac)
                * (inputs * torch.tensor(input_mask).to(inputs.device))
            )
            # calculate masked loss only on the output_mask part of the reconstruction
            inv_output_mask = torch.abs(
                torch.ones(output_mask.size()).to(targets.device) - output_mask
            )
            if self.gene_likelihood == "zinb":
                x_latent, mu, theta, pi = self(masked_inputs)
                loss = (
                    (
                        torch.tensor(inv_output_mask).to(inputs.device)
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta, pi), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta, pi))
            elif self.gene_likelihood == "nb":
                x_latent, mu, theta = self(masked_inputs)
                loss = (
                    (
                        torch.tensor(inv_output_mask).to(inputs.device)
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta))
            elif self.gene_likelihood == "poisson":
                x_latent, mu = self(masked_inputs)
                loss = (
                    (
                        torch.tensor(inv_output_mask).to(inputs.device)
                        * self._calc_reconstruction_loss(targets, mu, reduction="none")
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction(mu)

        elif self.masking_rate and self.masking_strategy == "gp_to_tf":
            with torch.no_grad():
                # self.encoded gene program is a Dict of encoded gene programs and the corresponding tf indices
                input_mask, output_mask = _only_activate_gene_program_numpy(
                    inputs, self.encoded_gene_program
                )
                # log the fraction of genes masked
                self.log("frac_genes_masked", frac)
            # upscale inputs to compensate for masking
            masked_inputs = (
                1.0
                / (1.0 - frac)
                * (inputs * torch.tensor(input_mask).to(inputs.device))
            )
            # calculate masked loss only on the output_mask part of the reconstruction
            inv_output_mask = torch.abs(
                torch.ones(output_mask.size()).to(targets.device) - output_mask
            )
            if self.gene_likelihood == "zinb":
                x_latent, mu, theta, pi = self(masked_inputs)
                loss = (
                    (
                        torch.tensor(inv_output_mask).to(inputs.device)
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta, pi), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta, pi))
            elif self.gene_likelihood == "nb":
                x_latent, mu, theta = self(masked_inputs)
                loss = (
                    (
                        torch.tensor(inv_output_mask).to(inputs.device)
                        * self._calc_reconstruction_loss(
                            targets, (mu, theta), reduction="none"
                        )
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction((mu, theta))
            elif self.gene_likelihood == "poisson":
                x_latent, mu = self(masked_inputs)
                loss = (
                    (
                        torch.tensor(inv_output_mask).to(inputs.device)
                        * self._calc_reconstruction_loss(targets, mu, reduction="none")
                    )
                    .sum(-1)
                    .mean()
                )
                x_reconst = self._calc_reconstruction(mu)

        # raise error if masking rate is not none but masking strategy is not implemented
        elif self.masking_rate and self.masking_strategy not in [
            "random",
            "gene_program",
        ]:
            raise ValueError(
                f"Masking strategy {self.masking_strategy} not implemented."
            )

        # raise error if masking strategy is not none but masking rate is 0.0
        elif self.masking_strategy and self.masking_rate == 0.0:
            raise ValueError(
                f"Masking rate is 0 ({self.masking_rate}),"
                f" but masking strategy {self.masking_strategy} is not None."
            )

        else:
            # x_latent, mu, theta = self(inputs.to(targets.device))
            out = self(inputs.to(targets.device))
            if self.gene_likelihood == "zinb":
                x_latent, mu, theta, pi = out
                loss = self._calc_reconstruction_loss(targets, (mu, theta, pi))
                x_reconst = self._calc_reconstruction((mu, theta, pi))
            elif self.gene_likelihood == "nb":
                x_latent, mu, theta = out
                loss = self._calc_reconstruction_loss(targets, (mu, theta))
                x_reconst = self._calc_reconstruction((mu, theta))
            elif self.gene_likelihood == "poisson":
                x_latent, mu = out
                loss = self._calc_reconstruction_loss(targets, mu)
                x_reconst = self._calc_reconstruction(mu)
            else:
                raise ValueError(f"Invalid gene_likelihood: {self.gene_likelihood}")

        return x_latent, loss, x_reconst

    def predict_embedding(self, batch):
        """
        Predict the embedding for a given batch.

        Args:
            batch (Dict[str, torch.Tensor]): Batch of input data.

        Returns:
            torch.Tensor: Embedding tensor.
        """
        return self.encoder(batch["X"])

    def training_step(self, batch, batch_idx):
        """
        Training step.

        Args:
            batch (Dict[str, torch.Tensor]): Batch of input data.
            batch_idx (int): Index of the current batch.

        Returns:
            torch.Tensor: Loss value.
        """
        if self.supervised_subset is not None:
            mask = batch["dataset_id"] == self.supervised_subset
            if not mask:
                return None

            batch = {key: value[mask] for key, value in batch.items()}
        x_latent, loss, _ = self._step(batch)
        self.log("train_loss", loss, on_epoch=True, on_step=True)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

        return loss

    def validation_step(self, batch, batch_idx):
        """
        Validation step.

        Args:
            batch (Dict[str, torch.Tensor]): Batch of input data.
            batch_idx (int): Index of the current batch.
        """
        if self.supervised_subset is not None:
            mask = batch["dataset_id"] == self.supervised_subset
            if not mask:
                return None

            batch = {key: value[mask] for key, value in batch.items()}
        x_latent, loss, _ = self._step(batch, training=False)
        self.log("val_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def test_step(self, batch, batch_idx):
        """
        Test step.

        Args:
            batch (Dict[str, torch.Tensor]): Batch of input data.
            batch_idx (int): Index of the current batch.
        """
        if self.supervised_subset is not None:
            mask = batch["dataset_id"] == self.supervised_subset
            batch = {key: value[mask] for key, value in batch.items()}
        x_latent, loss, x_reconst = self._step(batch, training=False)
        metrics = self.test_metrics(x_reconst, batch["X"])
        self.log_dict(metrics)
        self.log("test_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return metrics


class MLPClassifier(BaseClassifier):
    """
    Multi-Layer Perceptron (MLP) classifier for cell type classification.

    Args:
        gene_dim (int): Dimension of the gene input.
        type_dim (int): Dimension of the cell type output.
        class_weights (np.ndarray): Array of class weights for loss calculation.
        child_matrix (np.ndarray): Matrix representing the hierarchical relationship between cell types.
        units (List[int]): List of hidden unit sizes for the MLP.
        train_set_size (int): Size of the training set.
        val_set_size (int): Size of the validation set.
        batch_size (int): Batch size for training and inference.
        supervised_subset (Optional[int], optional): Subset of the data to use for supervised training. Defaults to None.
        dropout (float, optional): Dropout rate. Defaults to 0.0.
        learning_rate (float, optional): Learning rate for optimizer. Defaults to 0.005.
        weight_decay (float, optional): Weight decay for optimizer. Defaults to 0.1.
        optimizer (Callable[..., torch.optim.Optimizer], optional): Optimizer class. Defaults to torch.optim.AdamW.
        lr_scheduler (Callable, optional): Learning rate scheduler. Defaults to None.
        lr_scheduler_kwargs (Dict, optional): Additional keyword arguments for the learning rate scheduler. Defaults to None.
    """

    def __init__(
        self,
        gene_dim: int,
        type_dim: int,
        class_weights: np.ndarray,
        child_matrix: np.ndarray,
        units: List[int],
        train_set_size: int,
        val_set_size: int,
        batch_size: int,
        supervised_subset: Optional[int] = None,
        dropout: float = 0.0,
        learning_rate: float = 0.005,
        weight_decay: float = 0.1,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,
        lr_scheduler_kwargs: Dict = None,
    ):
        super(MLPClassifier, self).__init__(
            gene_dim=gene_dim,
            type_dim=type_dim,
            class_weights=class_weights,
            child_matrix=child_matrix,
            train_set_size=train_set_size,
            val_set_size=val_set_size,
            batch_size=batch_size,
            supervised_subset=supervised_subset,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            optimizer=optimizer,
            lr_scheduler=lr_scheduler,
            lr_scheduler_kwargs=lr_scheduler_kwargs,
        )

        self.classifier = MLP(
            in_channels=gene_dim,
            hidden_channels=units + [type_dim],
            dropout=dropout,
            inplace=False,
        )

    def _step(self, batch, training=True):
        """
        Perform a forward pass and calculate the loss for a batch.

        Args:
            batch (dict): Dictionary containing the input data batch.
            training (bool, optional): Flag indicating whether the model is in training mode. Defaults to True.

        Returns:
            torch.Tensor: Corrected predictions for the batch.
            torch.Tensor: Loss value for the batch.
        """
        logits = self(batch["X"])
        with torch.no_grad():
            preds = torch.argmax(logits, dim=1)
            preds_corrected, targets_corrected = self.hierarchy_correct(
                preds, batch["cell_type"]
            )
        if training:
            loss = F.cross_entropy(
                logits, batch["cell_type"], weight=self.class_weights
            )
        else:
            loss = F.cross_entropy(logits, targets_corrected)

        return preds_corrected, loss

    def predict_step(
        self, batch, batch_idx, dataloader_idx=None, predict_embedding=False
    ):
        """
        Perform a prediction step for a batch.

        Args:
            batch (tuple or dict): Input data batch.
            batch_idx (int): Index of the batch.
            dataloader_idx (int, optional): Index of the dataloader. Defaults to None.
            predict_embedding (bool, optional): Flag indicating whether to predict the embedding. Defaults to False.

        Returns:
            torch.Tensor or None: Predicted values for the batch.
            torch.Tensor or None: Target values for the batch.
        """
        if isinstance(batch, tuple):
            batch = batch[0]

        if batch_idx % self.gc_freq == 0:
            gc.collect()

        # Apply dataset_id filtering only if supervised_subset is set
        if self.supervised_subset is not None:
            
            # Ensure supervised_subset is a list or set
            if not isinstance(self.supervised_subset, (list, set)):
                self.supervised_subset = [self.supervised_subset]

            mask = torch.tensor([id in self.supervised_subset for id in batch["dataset_id"]], dtype=torch.bool, device=batch["dataset_id"].device)

            if not any(mask):
                return None
            
            filtered_batch = {key: value[mask] for key, value in batch.items()}

            if predict_embedding:
                return self.encoder(filtered_batch["X"]).detach(), filtered_batch[
                    "cell_type"
                ]
            else:
                preds_corrected, loss = self._step(filtered_batch, training=False)
                return preds_corrected, filtered_batch["cell_type"]

        else:
            if predict_embedding:
                return self.encoder(batch["X"]).detach(), filtered_batch["cell_type"]
            else:
                preds_corrected, loss = self._step(batch, training=False)
                return preds_corrected, batch["cell_type"]

    def forward_embedding(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass to compute the embedding from the MLP.
        The computed embedding is the output before the last Linear layer of the MLP.

        Args:
            x (torch.Tensor): Input tensor.

        Returns:
            torch.Tensor: Computed embedding tensor.
        """
        for i, layer in enumerate(self.classifier):
            x = layer(x)
            if i == len(self.classifier) - 2:
                break
        return x

    def predict_embedding(self, batch, batch_idx, dataloader_idx=None) -> torch.Tensor:
        """
        Function to predict the embedding from the given batch.

        Args:
            batch (dict): Input data batch.
            batch_idx (int): Index of the batch.
            dataloader_idx (int, optional): Index of the dataloader. Defaults to None.

        Returns:
            torch.Tensor: Predicted embedding tensor.
        """
        x = batch["X"]
        return self.forward_embedding(x)


class MLPBYOL(BaseAutoEncoder):
    def __init__(
        self,
        # fixed params
        gene_dim: int,
        units_encoder: List[int],
        # params from datamodule
        train_set_size: int,
        val_set_size: int,
        batch_size: int,  # to send a mock image to the BYOL model
        # contrastive learning params
        use_momentum: bool,
        p: float=0.5,  # likelihood to apply augmentations
        negbin_intensity: float=0.1,  # intensity of the negative binomial noise
        dropout_intensity: float=0.1,  # intensity of the dropout augmentation
        # model specific params
        lr: float = 0.005,
        weight_decay: float = 0.1,
        dropout: float = 0.1,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,
        lr_scheduler_kwargs: Dict = None,
        activation: Callable[[], torch.nn.Module] = nn.SELU,
    ):
        # check input
        assert 0.0 <= dropout <= 1.0

        self.train_set_size = train_set_size
        self.val_set_size = val_set_size
        self.batch_size = batch_size

        super(MLPBYOL, self).__init__(
            gene_dim=gene_dim,
            train_set_size=train_set_size,
            val_set_size=val_set_size,
            batch_size=batch_size,
            learning_rate=lr,
            weight_decay=weight_decay,
            optimizer=optimizer,
            lr_scheduler=lr_scheduler,
            lr_scheduler_kwargs=lr_scheduler_kwargs,
        )

        # assign inner model, that will be trained using the BYOL / SimSiam framework
        self.gene_dim = gene_dim
        self.batch_size = batch_size
        self.units_encoder = units_encoder
        self.activation = activation
        self.dropout = dropout
        self.inner_model = self._get_inner_model()

        self.byol = BYOL(
            net=self.inner_model,
            image_size=self.gene_dim,
            batch_size=self.batch_size, 
            p=p,  # likelihood to apply augmentations
            negbin_intensity=negbin_intensity,  # intensity of the negative binomial noise
            dropout_intensity=dropout_intensity,  # intensity of the dropout augmentation
            use_momentum=use_momentum,
        )


    def _get_inner_model(self):
        self.inner_model = MLP(
            in_channels=self.gene_dim,
            hidden_channels=self.units_encoder,
            activation_layer=self.activation,
            inplace=False,
            dropout=self.dropout,
        )
        return self.inner_model

    def _step(self, batch):
        loss = self.forward(batch)
        return loss

    def predict_embedding(self, batch, batch_idx):
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return self.encoder(batch["X"])

    def forward(self, batch):
        return self.byol(batch["X"])

    def training_step(self, batch, batch_idx):
        loss = self._step(batch)
        self.log("train_loss", loss, on_epoch=True)
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return loss

    def validation_step(self, batch, batch_idx):
        loss = self._step(batch)
        self.log("val_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def test_step(self, batch, batch_idx):
        loss = self._step(batch)
        self.log("test_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def predict_step(self, batch, batch_idx, dataloader_idx: Optional[int] = None):
        x_reconst, loss = self(batch)
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return x_reconst, batch


# helper
class DictAsAttributes:
    def __init__(self, dictionary):
        self.__dict__.update(dictionary)


class MLPBarlowTwins(BaseAutoEncoder):
    def __init__(
        self,
        # fixed params
        gene_dim: int,
        units_encoder: List[int],
        # params from datamodule
        train_set_size: int = 10000,
        val_set_size: int = 2000,
        batch_size: int = 2048,
        # contrastive learning params
        CHECKPOINT_PATH: str = None,
        negbin_intensity: float=0.1,  # intensity of the negative binomial noise
        dropout_intensity: float=0.1,  # intensity of the dropout augmentation
        learning_rate_weights: float = 0.2,
        learning_rate_biases: float = 0.0048,
        lambd: float = 0.0051,
        lr: float = 0.005,  # dummy here
        weight_decay: float = 1e-6,
        dropout: float = 0.0,
        optimizer: Callable[..., torch.optim.Optimizer] = torch.optim.AdamW,
        lr_scheduler: Callable = None,  # dummy here
        lr_scheduler_kwargs: Dict = None,  # dummy here
        activation: Callable[[], torch.nn.Module] = nn.SELU,
    ):
        # check input
        assert 0.0 <= dropout <= 1.0

        super(MLPBarlowTwins, self).__init__(
            gene_dim=gene_dim,
            train_set_size=train_set_size,
            val_set_size=val_set_size,
            batch_size=batch_size,
            learning_rate=lr,
            weight_decay=weight_decay,
            optimizer=optimizer,
            lr_scheduler=lr_scheduler,
            lr_scheduler_kwargs=lr_scheduler_kwargs,
            automatic_optimization=False,
        )

        self.save_hyperparameters(ignore=["gene_dim"])

        self.best_val_loss = np.inf
        self.best_train_loss = np.inf

        self.train_set_size = train_set_size
        self.val_set_size = val_set_size
        self.batch_size = batch_size
        self.weight_decay = weight_decay
        self.learning_rate_weights = learning_rate_weights
        self.learning_rate_biases = learning_rate_biases
        self.lambd = lambd

        self.loader_length = self.train_set_size // self.batch_size

        self.step = 0  # for optimizer

        # assign inner model, that will be trained using the BYOL / SimSiam framework
        self.gene_dim = gene_dim
        self.units_encoder = units_encoder
        self.activation = activation
        self.dropout = dropout
        self.batch_size = batch_size

        self.transform = Transform(negbin_intensity=negbin_intensity, dropout_intensity=dropout_intensity)
        self.CHECKPOINT_PATH = CHECKPOINT_PATH

        inner_model = self._get_inner_model()

        # Initialize the model-specific parameters
        self.dropout = dropout
        self.activation = activation
        self.units_encoder = units_encoder
        self.barlow_twins = self._get_barlow_twins_model(inner_model)

    def _get_barlow_twins_model(self, inner_model):
        args = (
            self._prepare_barlow_twins_args()
        )  # Prepare the Barlow Twins arguments (use the relevant params)
        self.barlow_twins = BarlowTwins(backbone=inner_model, args=args)
        return self.barlow_twins

    def _get_inner_model(self):
        self.inner_model = MLP(
            in_channels=self.gene_dim,
            hidden_channels=self.units_encoder,
            activation_layer=self.activation,
            inplace=False,
            dropout=self.dropout,
        )
        return self.inner_model
    
    def _prepare_barlow_twins_args(self):
        # Prepare Barlow Twins arguments based on the required parameters
        args = {
            # 'data': ...,  # Path to your dataset directory (from class B)
            # 'workers': 8,  # number of data loader workers
            "epochs": 1000,  # number of total epochs to run
            "batch_size": self.batch_size,  # mini-batch size
            "learning_rate_weights": self.learning_rate_weights,  # base learning rate for weights
            "learning_rate_biases": self.learning_rate_biases,
            # base learning rate for biases and batch norm parameters
            "weight-decay": self.weight_decay,  # weight decay
            "lambd": self.lambd,  # weight on off-diagonal terms
            "projector": "256-256-512-512",  # projector MLP
            # 'print_freq': 100,  # print frequency
            # 'checkpoint_dir': './checkpoint/'  # path to checkpoint directory
        }
        self.args = DictAsAttributes(args)
        return self.args

    def _step(self, batch):
        # For Multiomics, batch['X'] has additional dim to squeeze
        if batch["X"].dim() == 3:
            batch["X"] = batch["X"].squeeze(1)
        x_in = batch["X"]
        # Modify the forward pass to use the Barlow Twins model (from class B)
        loss = self(x_in)
        return loss

    def predict_embedding(self, batch, batch_idx):
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return self.encoder(batch["X"])

    def forward(self, batch):
        # Apply two different augmentations to the same image
        y1, y2 = self.transform(batch)
        # Compute the Barlow Twins loss
        loss = self.barlow_twins(y1, y2)
        return loss

    def training_step(self, batch, batch_idx):
        # Increment the step counter
        self.step += 1
        # Initialize the optimizer
        param_weights = []
        param_biases = []
        for param in self.barlow_twins.parameters():
            if param.ndim == 1:
                param_biases.append(param)
            else:
                param_weights.append(param)
        parameters = [{"params": param_weights}, {"params": param_biases}]
        opt = LARS(
            parameters,
            lr=0,
            weight_decay=self.weight_decay,
            weight_decay_filter=True,
            lars_adaptation_filter=True,
        )
        # Adjust the learning rate
        adjust_learning_rate(self.args, opt, self.loader_length, self.step)
        # Zero the gradient before loss computation
        opt.zero_grad()
        # Calculate the loss
        loss = self._step(batch)
        # Manual backward pass and optimizer step
        self.manual_backward(loss)
        opt.step()

        self.log("train_loss", loss, on_epoch=True)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

        if loss < self.best_train_loss:
            self.best_train_loss = loss
            self.barlow_twins.save_model(
                path=self.CHECKPOINT_PATH + "/best_checkpoint_train.ckpt"
            )

        self.barlow_twins.save_model(
            path=self.CHECKPOINT_PATH + "/last_checkpoint.ckpt"
        )

        return loss

    def validation_step(self, batch, batch_idx):
        loss = self._step(batch)
        self.log("val_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

        if loss < self.best_val_loss:
            self.best_val_loss = loss
            self.barlow_twins.save_model(
                path=self.CHECKPOINT_PATH + "/best_checkpoint_val.ckpt"
            )

    def test_step(self, batch, batch_idx):
        loss = self._step(batch)
        self.log("test_loss", loss)
        if batch_idx % self.gc_freq == 0:
            gc.collect()

    def predict_step(self, batch, batch_idx, dataloader_idx: Optional[int] = None):
        x_reconst, loss = self(batch)
        if batch_idx % self.gc_freq == 0:
            gc.collect()
        return x_reconst, batch
