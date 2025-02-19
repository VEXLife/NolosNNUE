import lightning as L
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from einops.layers.torch import Rearrange
from einops import rearrange


class Encoder(nn.Module):
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

    def forward(self, x):
        x = self.conv1(x)
        x = self.prelu1(x)
        x = self.conv2(x)
        x = self.prelu2(x)
        x = Rearrange('b c h w -> b (c h w)')(x)  # 512 x 11 x 11
        return x


class Critic(nn.Module):
    def __init__(self):
        super().__init__()
        self.forward = self.q
        self.encoder = Encoder()
        self.fc1 = nn.Linear(512 * 11 * 11 + 15 * 15, 32)
        self.prelu1 = nn.PReLU()
        self.fc2 = nn.Linear(32, 1)

    def q(self, boards, action_probs):
        x = self.encoder(boards)
        x = torch.cat([x, action_probs], dim=1)
        x = self.fc1(x)
        x = self.prelu1(x)
        x = self.fc2(x)
        return x
    


class Actor(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = Encoder()
        self.fc1 = nn.Linear(512 * 11 * 11, 32)
        self.prelu1 = nn.PReLU()
        self.fc2 = nn.Linear(32, 225)

    def forward(self, x):
        x = self.encoder(x)
        x = self.fc1(x)
        x = self.prelu1(x)
        x = self.fc2(x)
        x = F.softmax(x, dim=1)
        return x

# Use TD3+BC algorithm to train the model


class LitTD3BC(L.LightningModule):
    def __init__(self, **kwargs):
        super().__init__()
        self.actor = Actor(**kwargs)
        self.critic1 = Critic(**kwargs)
        self.critic2 = Critic(**kwargs)
        self.actor_target = Actor(**kwargs)
        self.critic1_target = Critic(**kwargs)
        self.critic2_target = Critic(**kwargs)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.critic1_target.load_state_dict(self.critic1.state_dict())
        self.critic2_target.load_state_dict(self.critic2.state_dict())
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=1e-4)
        self.critic1_optimizer = optim.Adam(self.critic1.parameters(), lr=1e-4)
        self.critic2_optimizer = optim.Adam(self.critic2.parameters(), lr=1e-4)
        self.critic_criterion = nn.MSELoss()
        self.automatic_optimization = False

    def predict_step(self, batch, batch_idx, dataloader_idx=None):
        x, _ = batch
        return self.actor(x)

    def training_step(self, batch, batch_idx):
        boards, next_boards, rewards, actions = batch
        actions = rearrange(actions, "b 1 -> b")
        opt_actor, opt_critic1, opt_critic2 = self.optimizers()

        # # Critic update (always performed)
        # actions_one_hot = F.one_hot(actions, num_classes=225).float()
        # q_values1 = self.critic1.q(boards, actions_one_hot)
        # q_values2 = self.critic2.q(boards, actions_one_hot)

        # with torch.no_grad():
        #     next_actions_prob = self.actor_target(next_boards)
        #     noise = torch.normal(0, 0.2, next_actions_prob.shape)
        #     next_actions = torch.argmax(next_actions_prob + noise, dim=1)
        #     next_actions_one_hot = F.one_hot(next_actions, num_classes=225).float()
        #     next_q_values1 = self.critic1_target.q(next_boards, next_actions_one_hot)
        #     next_q_values2 = self.critic2_target.q(next_boards, next_actions_one_hot)
        #     target_q_values = rewards + \
        #         (rewards == 0) * torch.min(next_q_values1, next_q_values2)
        # critic1_loss = self.critic_criterion(q_values1, target_q_values)
        # critic2_loss = self.critic_criterion(q_values2, target_q_values)

        # opt_critic1.zero_grad()
        # self.manual_backward(critic1_loss)
        # opt_critic1.step()
        # opt_critic2.zero_grad()
        # self.manual_backward(critic2_loss)
        # opt_critic2.step()

        # # Delayed policy (actor) update every 2 steps
        # if batch_idx % 2 == 0:
        #     actions_pred_probs = self.actor(boards)
        #     actions_pred = torch.argmax(actions_pred_probs, dim=1)
        #     actions_pred_one_hot = F.one_hot(actions_pred, num_classes=225).float()
        #     actor_loss_td3 = -self.critic1.q(boards, actions_pred_one_hot).mean()
        #     bc_loss = F.cross_entropy(actions_pred_probs, actions)
        #     actor_loss = actor_loss_td3 + 2.5 * bc_loss

        #     opt_actor.zero_grad()
        #     self.manual_backward(actor_loss)
        #     opt_actor.step()

        #     self.log('actor_loss', actor_loss, prog_bar=True, logger=True)

        # self.log('critic1_loss', critic1_loss, prog_bar=True, logger=True)
        # self.log('critic2_loss', critic2_loss, prog_bar=True, logger=True)

        
        actions_pred_probs = self.actor(boards)
        bc_loss = F.cross_entropy(actions_pred_probs, actions)
        actor_loss = bc_loss

        opt_actor.zero_grad()
        self.manual_backward(actor_loss)
        opt_actor.step()

        self.log('actor_loss', actor_loss, prog_bar=True, logger=True)

    def configure_optimizers(self):
        return [self.actor_optimizer, self.critic1_optimizer, self.critic2_optimizer]

    def on_epoch_end(self):
        for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
            target_param.data = 0.995 * target_param.data + 0.005 * param.data
        for param, target_param in zip(self.critic1.parameters(), self.critic1_target.parameters()):
            target_param.data = 0.995 * target_param.data + 0.005 * param.data
        for param, target_param in zip(self.critic2.parameters(), self.critic2_target.parameters()):
            target_param.data = 0.995 * target_param.data + 0.005 * param.data
