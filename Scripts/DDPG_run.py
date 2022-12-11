# -*- coding: utf-8 -*-

import os
import numpy as np
import gym
import panda_gym
from multiprocessing import Pool
from DDPGNetwork import Agent
import time


def run(run):
    cwd = os.path.dirname(os.path.realpath(__file__))

    global EXP_NAME, TASK, REWARD

    env = gym.make(f"Panda{TASK}{REWARD}-v2", render=False)

    os.makedirs(f"{cwd}/../Data/{EXP_NAME}/Run_{run}", exist_ok=True)
    obs = env.reset()
    obs_dim = len(np.concatenate([obs["observation"], obs["desired_goal"]]))
    agent = Agent(
        alpha=0.0001,
        beta=0.001,
        input_dims=[obs_dim],
        tau=0.001,
        batch_size=64,
        layer1_size=400,
        layer2_size=300,
        n_actions=env.action_space.shape[0],
    )
    score_history, actor_loss, critic_loss = [], [], []
    for i in range(1400):
        observation = env.reset()
        observation = np.concatenate(
            [observation["observation"], observation["desired_goal"]]
        )
        done = False
        score = 0
        agent.noise.reset()
        while not done:
            action = agent.choose_action(observation)
            new_state, reward, done, info = env.step(action)
            new_state = np.concatenate(
                [new_state["observation"], new_state["desired_goal"]]
            )
            agent.remember(observation, action, reward, new_state, done)
            agent.learn()
            score += reward
            obs = new_state

        actor_loss.append(agent.actor_loss)
        critic_loss.append(agent.critic_loss)
        score_history.append(score)
        os.makedirs(f"{cwd}/../Data/{EXP_NAME}/Run_{run}/", exist_ok=True)
        if i % 500 == 0:
            print(
                f"Saving score_history to {cwd}/../Data/{EXP_NAME}/Run_{run}/Run_{run}_Ep_{i}.npy",
                flush=True,
            )
            np.save(
                f"{cwd}/../Data/{EXP_NAME}/Run_{run}/Run_{run}_Ep_{i}.npy",
                np.array(score_history),
            )

        print(
            "Run: ",
            run,
            "Episode ",
            i,
            "Score %.2f" % score,
            "Trailing 100 games avg %.3f" % np.mean(score_history[-100:]),
            flush=True,
        )

    os.makedirs(f"{cwd}/../Data/{EXP_NAME}/Actor_loss", exist_ok=True)
    actor_loss = actor_loss[1:]
    np.save(
        f"{cwd}/../Data/{EXP_NAME}/Actor_loss/Actor_loss_run_{run}.npy",
        np.array(actor_loss),
    )

    os.makedirs(f"{cwd}/../Data/{EXP_NAME}/Critic_loss", exist_ok=True)
    critic_loss = critic_loss[1:]
    np.save(
        f"{cwd}/../Data/{EXP_NAME}/Critic_loss/Critic_loss_run_{run}.npy",
        np.array(critic_loss),
    )
    np.save(f"{cwd}/../Data/{EXP_NAME}/Run_{run}.npy", np.array(score_history))
    env.close()
    return score_history


def DDPG_main():
    global EXP_NAME, TASK, REWARD
    EXP_NAME = input("Enter experiment name: ")
    task_list = ["Reach", "Push", "PickAndPlace", "Slide", "Stack"]
    TASK = task_list[
        int(
            input(
                f"Enter task number {task_list}. Enter a number from 0 to {len(task_list) - 1}: "
            )
        )
    ]

    reward_list = ["Dense", ""]
    REWARD = reward_list[int(input("Enter reward type (Dense = 0; Sparse = 1): "))]

    NoRuns = int(input("Enter number of runs: "))
    rList = np.arange(NoRuns, dtype=int).tolist()

    start = time.time()
    print(f"Starting {EXP_NAME}", flush=True)

    run_scores = []
    pool = Pool(processes=NoRuns)
    run_scores = pool.map_async(run, rList).get()
    pool.close()
    run_scores = np.array(run_scores)
    print(
        f"Time taken to run: {run_scores.shape[0]} runs with {run_scores.shape[1]} episodes each: {time.time() - start}"
    )


if __name__ == "__main__":
    DDPG_main()
