import lightning as L
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from einops.layers.torch import Rearrange

class ConvNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(
            in_channels=1,
            out_channels=128,
            kernel_size=3,
        )
        self.fc1 = nn.Linear(128*6*6, 128)
        self.fc2 = nn.Linear(128, 1)

    def forward(self, x):
        x = self.conv1(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = Rearrange('b c h w -> b (c h w)')(x)
        x = self.fc1(x)
        x = F.relu(x)
        x = self.fc2(x)
        output = F.tanh(x)
        return output

class LitConvNet(L.LightningModule):
    def __init__(self, **kwargs):
        super().__init__()
        self.model = ConvNet(**kwargs)

    def predict_step(self, batch, batch_idx, dataloader_idx=None):
        x, _ = batch
        return self(x)

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)
        loss = F.mse_loss(y_hat, y)
        self.log('train/loss', loss)
        return loss

    def configure_optimizers(self):
        return optim.Adam(self.parameters(), lr=0.001)
