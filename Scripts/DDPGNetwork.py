import os
import torch as T
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np
import matplotlib.pyplot as plt
import pickle


class OUActionNoise(object):
    def __init__(self, mu, sigma=0.15, theta=0.2, dt=1e-2, x0=None):
        self.theta = theta
        self.mu = mu
        self.sigma = sigma
        self.dt = dt
        self.x0 = x0
        self.reset()

    def __call__(self):
        x = (
            self.x_prev
            + self.theta * (self.mu - self.x_prev) * self.dt
            + self.sigma * np.sqrt(self.dt) * np.random.normal(size=self.mu.shape)
        )
        self.x_prev = x
        return x

    def reset(self):
        self.x_prev = self.x0 if self.x0 is not None else np.zeros_like(self.mu)

    def __repr__(self):
        return "OrnsteinUhlenbeckActionNoise(mu={}, sigma={})".format(
            self.mu, self.sigma
        )


class ReplayBuffer(object):
    def __init__(self, max_size, input_shape, n_actions):
        self.mem_size = max_size
        self.mem_cntr = 0
        self.state_memory = np.zeros((self.mem_size, *input_shape))
        self.new_state_memory = np.zeros((self.mem_size, *input_shape))
        self.action_memory = np.zeros((self.mem_size, n_actions))
        self.reward_memory = np.zeros(self.mem_size)
        self.terminal_memory = np.zeros(self.mem_size, dtype=bool)

    def store_transition(self, state, action, reward, state_, done):
        index = self.mem_cntr % self.mem_size
        self.state_memory[index] = state
        self.new_state_memory[index] = state_
        self.action_memory[index] = action
        self.reward_memory[index] = reward
        self.terminal_memory[index] = 1 - done
        # self.terminal_memory[index] = done
        self.mem_cntr += 1

    def sample_buffer(self, batch_size):
        max_mem = min(self.mem_cntr, self.mem_size)

        batch = np.random.choice(max_mem, batch_size)

        states = self.state_memory[batch]
        actions = self.action_memory[batch]
        rewards = self.reward_memory[batch]
        states_ = self.new_state_memory[batch]
        terminal = self.terminal_memory[batch]

        return states, actions, rewards, states_, terminal


class CriticNetwork(nn.Module):
    def __init__(
        self,
        beta,
        input_dims,
        fc1_dims,
        fc2_dims,
        n_actions,
        name,
        chkpt_dir="tmp/ddpg",
    ):
        super(CriticNetwork, self).__init__()
        # try starting with a small beta and then increase the beta after a few episodes when the critic loss is small
        self.input_dims = input_dims
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.n_actions = n_actions
        self.checkpoint_file = os.path.join(chkpt_dir, name + "_ddpg")
        self.device = T.device("cuda:0")

        self.fc1 = nn.Linear(*self.input_dims, self.fc1_dims).to(self.device)
        f1 = 1.0 / np.sqrt(self.fc1.weight.data.size()[0])
        T.nn.init.uniform_(self.fc1.weight.data, -f1, f1).to(self.device)
        T.nn.init.uniform_(self.fc1.bias.data, -f1, f1).to(self.device)
        self.bn1 = nn.LayerNorm(self.fc1_dims).to(self.device)

        self.fc2 = nn.Linear(self.fc1_dims, self.fc2_dims).to(self.device)
        f2 = 1.0 / np.sqrt(self.fc2.weight.data.size()[0])

        T.nn.init.uniform_(self.fc2.weight.data, -f2, f2).to(self.device)
        T.nn.init.uniform_(self.fc2.bias.data, -f2, f2).to(self.device)

        self.bn2 = nn.LayerNorm(self.fc2_dims).to(self.device)
        # self.bn1 = nn.BatchNorm1d(self.fc1_dims).to(self.device)
        # self.bn2 = nn.BatchNorm1d(self.fc2_dims).to(self.device)

        self.action_value = nn.Linear(self.n_actions, self.fc2_dims).to(self.device)
        f4 = 0.003
        self.q = nn.Linear(self.fc2_dims, 1).to(self.device)
        T.nn.init.uniform_(self.q.weight.data, -f4, f4).to(self.device)
        T.nn.init.uniform_(self.q.bias.data, -f4, f4).to(self.device)

        self.optimizer = optim.Adam(self.parameters(), lr=beta)

        self.to(self.device)

    def forward(self, state, action):
        state_value = self.fc1(state).to(self.device)
        state_value = self.bn1(state_value).to(self.device)
        state_value = F.relu(state_value).to(self.device)
        state_value = self.fc2(state_value).to(self.device)
        state_value = self.bn2(state_value).to(self.device)
        state_value = F.relu(state_value).to(self.device)

        action_value = F.relu(self.action_value(action)).to(self.device)
        state_action_value = F.relu(T.add(state_value, action_value)).to(self.device)
        state_action_value = self.q(state_action_value).to(self.device)

        return state_action_value

    def save_checkpoint(self):
        print("... Saving Checkpoint ...", flush=True)
        T.save(self.state_dict(), self.checkpoint_file)

    def load_checkpoint(self):
        print("... Loading Checkpoint ...", flush=True)
        self.load_state_dict(T.load(self.checkpoint_file))


class ActorNetwork(nn.Module):
    def __init__(
        self,
        alpha,
        input_dims,
        fc1_dims,
        fc2_dims,
        n_actions,
        name,
        chkpt_dir="tmp/ddpg",
    ):
        super(ActorNetwork, self).__init__()
        self.device = T.device("cuda:0")

        self.input_dims = input_dims
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.n_actions = n_actions
        self.checkpoint_file = os.path.join(chkpt_dir, name + "_ddpg")

        self.fc1 = nn.Linear(*self.input_dims, self.fc1_dims).to(self.device)
        f1 = 1.0 / np.sqrt(self.fc1.weight.data.size()[0])
        T.nn.init.uniform_(self.fc1.weight.data, -f1, f1).to(self.device)
        T.nn.init.uniform_(self.fc1.bias.data, -f1, f1).to(self.device)
        self.bn1 = nn.LayerNorm(self.fc1_dims).to(self.device)

        self.fc2 = nn.Linear(self.fc1_dims, self.fc2_dims).to(self.device)
        # f2 = 0.002
        f2 = 1.0 / np.sqrt(self.fc2.weight.data.size()[0])
        T.nn.init.uniform_(self.fc2.weight.data, -f2, f2).to(self.device)
        T.nn.init.uniform_(self.fc2.bias.data, -f2, f2).to(self.device)
        self.bn2 = nn.LayerNorm(self.fc2_dims).to(self.device)

        f4 = 0.003
        self.mu = nn.Linear(self.fc2_dims, self.n_actions).to(self.device)
        T.nn.init.uniform_(self.mu.weight.data, -f4, f4).to(self.device)
        T.nn.init.uniform_(self.mu.bias.data, -f4, f4).to(self.device)

        self.optimizer = optim.Adam(self.parameters(), lr=alpha)
        self.to(self.device)

    def forward(self, state):
        x = self.fc1(state).to(self.device)
        x = self.bn1(x).to(self.device)
        x = F.relu(x).to(self.device)
        x = self.fc2(x).to(self.device)
        x = self.bn2(x).to(self.device)
        x = F.relu(x).to(self.device)
        x = T.tanh(self.mu(x)).to(self.device)

        return x

    def save_checkpoint(self):
        print("... Saving Checkpoint ...", flush=True)
        T.save(self.state_dict(), self.checkpoint_file)

    def load_checkpoint(self):
        print("... Loading Checkpoint ...", flush=True)
        self.load_state_dict(T.load(self.checkpoint_file))


class Agent(object):
    def __init__(
        self,
        alpha,
        beta,
        tau,
        n_actions,
        input_dims,
        layer1_size,
        layer2_size,
        batch_size,
        gamma=0.99,
        max_size=100000,
    ):
        self.gamma = gamma
        self.tau = tau
        self.memory = ReplayBuffer(max_size, input_dims, n_actions)
        self.batch_size = batch_size
        self.noise = OUActionNoise(mu=np.zeros(n_actions))

        self.actor = ActorNetwork(
            alpha,
            input_dims,
            layer1_size,
            layer2_size,
            n_actions=n_actions,
            name="Actor",
        )
        self.critic = CriticNetwork(
            beta,
            input_dims,
            layer1_size,
            layer2_size,
            n_actions=n_actions,
            name="Critic",
        )

        self.target_actor = ActorNetwork(
            alpha,
            input_dims,
            layer1_size,
            layer2_size,
            n_actions=n_actions,
            name="TargetActor",
        )
        self.target_critic = CriticNetwork(
            beta,
            input_dims,
            layer1_size,
            layer2_size,
            n_actions=n_actions,
            name="TargetCritic",
        )

        self.actor_loss, self.critic_loss = [], []
        self.update_network_parameters(tau=1)

    def choose_action(self, observation):
        self.actor.eval()
        observation = T.tensor(observation, dtype=T.float).to(self.actor.device)
        mu = self.actor.forward(observation).to(self.actor.device)
        mu_prime = mu + T.tensor(self.noise(), dtype=T.float).to(self.actor.device)
        self.actor.train()
        return mu_prime.cpu().detach().numpy()

    def remember(self, state, action, reward, new_state, done):
        self.memory.store_transition(state, action, reward, new_state, done)

    def learn(self):
        if self.memory.mem_cntr < self.batch_size:
            return
        state, action, reward, new_state, done = self.memory.sample_buffer(
            self.batch_size
        )

        state = T.tensor(state, dtype=T.float).to(self.critic.device)
        action = T.tensor(action, dtype=T.float).to(self.critic.device)
        reward = T.tensor(reward, dtype=T.float).to(self.critic.device)
        new_state = T.tensor(new_state, dtype=T.float).to(self.critic.device)
        done = T.tensor(done).to(self.critic.device)

        self.target_actor.eval()
        self.target_critic.eval()
        self.critic.eval()
        target_actions = self.target_actor.forward(new_state)
        critic_value_ = self.target_critic.forward(new_state, target_actions)
        critic_value = self.critic.forward(state, action)

        target = []
        for j in range(self.batch_size):
            target.append(reward[j] + self.gamma * critic_value_[j] * int(done[j]))

        target = T.tensor(target).to(self.critic.device)
        target = target.view(self.batch_size, 1)

        self.critic.train()
        self.critic.optimizer.zero_grad()
        critic_loss = F.mse_loss(target, critic_value)
        critic_loss.backward()
        self.critic_loss = critic_loss.item()
        self.critic.optimizer.step()

        self.critic.eval()
        self.actor.optimizer.zero_grad()
        mu = self.actor.forward(state)
        self.actor.train()
        actor_loss = -self.critic.forward(state, mu)
        actor_loss = T.mean(actor_loss)
        actor_loss.backward()
        self.actor_loss = actor_loss.item()
        self.actor.optimizer.step()

        self.update_network_parameters()

    def update_network_parameters(self, tau=None):
        if tau is None:
            tau = self.tau

        actor_params = self.actor.named_parameters()
        critic_params = self.critic.named_parameters()
        target_actor_params = self.target_actor.named_parameters()
        target_critic_params = self.target_critic.named_parameters()

        critic_state_dict = dict(critic_params)
        actor_state_dict = dict(actor_params)
        target_critic_state_dict = dict(target_critic_params)
        target_actor_state_dict = dict(target_actor_params)

        for name in critic_state_dict:
            critic_state_dict[name] = (
                tau * critic_state_dict[name].clone()
                + (1 - tau) * target_critic_state_dict[name].clone()
            )

        self.target_critic.load_state_dict(critic_state_dict)

        for name in actor_state_dict:
            actor_state_dict[name] = (
                tau * actor_state_dict[name].clone()
                + (1 - tau) * target_actor_state_dict[name].clone()
            )

        self.target_actor.load_state_dict(actor_state_dict)

    def save_models(self):
        self.actor.save_checkpoint()
        self.target_actor.save_checkpoint()
        self.critic.save_checkpoint()
        self.target_critic.save_checkpoint()

    def load_models(self):
        self.actor.load_checkpoint()
        self.target_actor.load_checkpoint()
        self.critic.load_checkpoint()
        self.target_critic.load_checkpoint()

    def check_actor_params(self):
        current_actor_params = self.actor.named_parameters()
        current_actor_dict = dict(current_actor_params)
        original_actor_dict = dict(self.original_actor.named_parameters())
        original_critic_dict = dict(self.original_critic.named_parameters())
        current_critic_params = self.critic.named_parameters()
        current_critic_dict = dict(current_critic_params)
        print("Checking Actor parameters")

        for param in current_actor_dict:
            print(param, T.equal(original_actor_dict[param], current_actor_dict[param]))
        print("Checking critic parameters")
        for param in current_critic_dict:
            print(
                param, T.equal(original_critic_dict[param], current_critic_dict[param])
            )
        input()
