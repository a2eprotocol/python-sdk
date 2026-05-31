from a2e.caps.env.client import EnvAPI
from a2e.caps.env.protocol import EnvStatePush


def on_env_push(push: EnvStatePush):
    """Receive server-initiated environment state push events."""
    print(f"  [env.push] event_type={push.event_type} | reason={push.reason}")
    if push.delta:
        print(f"  [env.push] delta={push.delta}")
    if push.terminal:
        print(f"  [env.push] EPISODE TERMINAL")


def run_env(client):
    env = EnvAPI(client)

    # Register a push handler before starting — catches async state pushes
    env.on_push(on_env_push)

    resp = env.reset(env_name="counter_env")
    obs = resp.obs
    episode_id = obs.episode_id
    done = obs.done
    truncated = obs.truncated
    while not env.is_done(done, truncated):
        action = {
            "type": "inc",
        }

        step_resp = env.step(episode_id, action)
        print(step_resp)
        done = step_resp.done
        truncated = step_resp.truncated
        #review_data = env.review(obs, {"threshold": 0.7})

        # plug into workflow / learn
        #runner.run(chain_id="eval", input_state=review_data)

    resp = env.observe(episode_id=episode_id)
    print(resp.obs)

    resp = env.reset(env_name="counter_env")
    print(resp.obs)
