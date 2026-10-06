"""patches/harbor-train-9310ef6.patch against the pristine generator: Harbor 0.23 trial construction and the PLAN.md
§6.4 timeout policy (reward 0, trained on the saved transcript; per-trajectory mask without one; infrastructure errors
still mask the whole prompt group). Skipped unless a harbor-train clone is available (HARBOR_TRAIN_DIR or ../ext)."""
import asyncio
import importlib.util
import os
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PATCH = REPO / "patches" / "harbor-train-9310ef6.patch"
HT = Path(os.environ.get("HARBOR_TRAIN_DIR", REPO.parent / "ext" / "harbor-train"))
REL = "skyrl-train/examples/harbor/harbor_generator.py"

pytestmark = pytest.mark.skipif(not (HT / ".git").exists(), reason="harbor-train clone not available")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules.setdefault(name, mod)


@dataclass(frozen=True)
class TrajectoryID:
    instance_id: str
    repetition_id: int


def _resp_ids(messages, tokenizer, logprobs, chat_template=None):
    ids, mask = [], []
    for m in messages:
        ids.append(len(ids) + 10)
        mask.append(1 if m["role"] == "assistant" else 0)
    return ids, mask, None


@pytest.fixture(scope="module")
def gen(tmp_path_factory):
    d = tmp_path_factory.mktemp("ht")
    pristine = subprocess.run(["git", "-C", str(HT), "show", f"9310ef653ae6af33d1ec11d477fdc9689461ec41:{REL}"],
                              check=True, capture_output=True).stdout
    (d / "skyrl-train/examples/harbor").mkdir(parents=True)
    (d / REL).write_bytes(pristine)
    subprocess.run(["patch", "-p1", "-s", "-d", str(d), "-i", str(PATCH)], check=True)

    log = types.SimpleNamespace(**{k: (lambda *a, **k: None) for k in ["info", "debug", "warning", "error"]})
    _stub("loguru", logger=log)
    _stub("omegaconf", DictConfig=dict, OmegaConf=types.SimpleNamespace(to_container=lambda c, resolve=True: c))
    for pkg in ["skyrl_train", "skyrl_train.generators", "skyrl_train.inference_engines", "skyrl_train.utils"]:
        _stub(pkg)
    _stub("skyrl_train.generators.base", GeneratorInterface=object, GeneratorInput=dict, GeneratorOutput=dict,
          TrajectoryID=TrajectoryID)
    _stub("skyrl_train.generators.utils", get_rollout_metrics=lambda ids, rewards: {},
          get_response_ids_and_loss_mask_from_messages=_resp_ids)
    _stub("skyrl_train.inference_engines.inference_engine_client", InferenceEngineClient=object)
    _stub("skyrl_train.inference_engines.base", ConversationType=list)
    _stub("skyrl_train.utils.rate_limiter", create_rate_limiter=lambda cfg: None)

    spec = importlib.util.spec_from_file_location("patched_harbor_generator", d / REL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Limiter:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _results(exc=None, reward=None, messages="default"):
    msgs = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "a"}] if messages == "default" else messages
    md = None if messages is None else {"all_messages": msgs, "summarization_count": 0, "n_episodes": 1}
    return types.SimpleNamespace(
        exception_info=types.SimpleNamespace(exception_type=exc) if exc else None,
        verifier_result=types.SimpleNamespace(rewards={"reward": reward}) if reward is not None else None,
        agent_result=types.SimpleNamespace(metadata=md))


def _generator(gen, results_seq):
    calls = {"create": 0}
    seq = iter(results_seq)

    class FakeTrial:
        def __init__(self, *a, **k):
            raise ValueError("Instantiating Trial directly is deprecated. Use `await Trial.create(config)` instead.")

        @classmethod
        async def create(cls, config):
            calls["create"] += 1
            t = object.__new__(cls)
            t.res = next(seq)
            return t

        async def run(self):
            return self.res

    gen.Trial = FakeTrial
    gen.TrialConfig = types.SimpleNamespace(model_validate=lambda c: c)
    g = object.__new__(gen.HarborGenerator)
    g._harbor_trial_config_template = {"agent": {"kwargs": {}}}
    g._rate_limiter = _Limiter()
    g.tokenizer = types.SimpleNamespace(apply_chat_template=lambda *a, **k: [1, 2, 3])
    g.custom_chat_template_content = None
    g.max_seq_len = 32768
    g.generator_cfg = types.SimpleNamespace(apply_overlong_filtering=True)
    return g, calls


def _run(g, inst="t", rep=0):
    return asyncio.run(g.harbor_agent_loop(prompt="tasks/x", trajectory_id=TrajectoryID(inst, rep)))


def test_trial_created_via_async_factory(gen):
    g, calls = _generator(gen, [_results(reward=1.0)])
    out = _run(g)
    assert calls["create"] == 1 and out.reward == 1.0 and out.stop_reason == "complete" and 1 in out.loss_mask


def test_timeout_with_transcript_trains_with_zero_reward(gen):
    g, calls = _generator(gen, [_results(exc="AgentTimeoutError", reward=1.0)])
    out = _run(g)
    assert calls["create"] == 1                      # no retry
    assert out.reward == 0 and out.stop_reason == "agent_timeout" and 1 in out.loss_mask


@pytest.mark.parametrize("messages", [None, [{"role": "user", "content": "task"}]])
def test_timeout_without_usable_transcript_masks_only_that_trajectory(gen, messages):
    g, calls = _generator(gen, [_results(exc="AgentTimeoutError", messages=messages)])
    out = _run(g)
    assert calls["create"] == 1
    assert out.reward == 0 and out.stop_reason == "agent_timeout_excluded" and out.loss_mask == [0]


def test_group_masking_only_for_infrastructure_errors(gen):
    g, _ = _generator(gen, [_results(reward=1.0), _results(exc="AgentTimeoutError"),
                            _results(exc="AgentTimeoutError", messages=None),
                            _results(), _results(),               # group b: no verifier result twice -> error
                            _results(reward=1.0)])
    outs = [_run(g, "a", 0), _run(g, "a", 1), _run(g, "a", 2), _run(g, "b", 0), _run(g, "b", 1)]
    outs, metrics = gen.HarborGenerator._mask_failed_instances_and_compute_metrics(outs)
    a, b = outs[:3], outs[3:]
    assert [o.stop_reason for o in a] == ["complete", "agent_timeout", "agent_timeout_excluded"]
    assert [o.reward for o in a] == [1.0, 0, 0]       # excluded timeout still counts as a failure in the baseline
    assert 1 in a[0].loss_mask and 1 in a[1].loss_mask and a[2].loss_mask == [0]
    assert all(o.stop_reason == "error" and o.loss_mask == [0] for o in b)
    assert b[0].reward == 0 and b[1].reward == 0      # group b masked, including its successful member
    assert metrics["generate/num_timeout_trajectories"] == 2
    assert metrics["generate/num_timeout_excluded_trajectories"] == 1
    assert metrics["generate/num_masked_instances"] == 1
