import lightning as L
import torch
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
        self.prelu1 = nn.PReLU()
        self.conv2 = nn.Conv2d(
            in_channels=128,
            out_channels=512,
            kernel_size=3,
        )
        self.prelu2 = nn.PReLU()
        self.fc1 = nn.Linear(512, 32)
        self.prelu3 = nn.PReLU()
        self.fc2 = nn.Linear(32, 1)

    def forward(self, x):
        x = self.conv1(x)
        x = self.prelu1(x)
        x = self.conv2(x)
        x = self.prelu2(x)
        x = F.max_pool2d(x, x.shape[-1])
        x = Rearrange('b c h w -> b (c h w)')(x)
        x = self.fc1(x)
        x = self.prelu3(x)
        x = self.fc2(x)
        output = F.tanh(x)
        return output

class LitConvNet(L.LightningModule):
    def __init__(self, **kwargs):
        super().__init__()
        self.model = ConvNet(**kwargs)

    def predict_step(self, batch, batch_idx, dataloader_idx=None):
        x, _ = batch
        return self.model(x)

    def training_step(self, batch, batch_idx):
        x, y, a = batch
        y_hat = self.model(x)
        loss = F.mse_loss(y_hat, y)
        self.log('train/loss', loss)
        return loss
    
    def validation_step(self, batch, batch_idx):
        x, y, a = batch
        y_hat = self.model(x)
        # Quantize y_hat to (-1,1), if y_hat is closer to 1, then set it to 1, otherwise -1
        y_hat = torch.where(y_hat > 0, torch.ones_like(y_hat), -torch.ones_like(y_hat))
        acc = (y_hat == y).float().mean()
        self.log('val/acc', acc)
        return acc

    def configure_optimizers(self):
        return optim.Adam(self.parameters(), lr=0.0001)
