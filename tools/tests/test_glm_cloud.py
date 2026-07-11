from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_glm_cloud_matches_working_ccs_profile() -> None:
    config = yaml.safe_load(
        (ROOT / "modules/llm-litellm/files/etc/aipc/litellm/config.yaml").read_text()
    )
    model = next(item for item in config["model_list"] if item["model_name"] == "glm-cloud")

    assert model["litellm_params"] == {
        "model": "anthropic/glm-5.2",
        "api_base": "https://api.z.ai/api/anthropic",
        "api_key": "os.environ/Z_AI_API_KEY",
        "timeout": 180,
        "num_retries": 0,
    }


def test_glm_cloud_registry_and_secret_plumbing() -> None:
    models = yaml.safe_load(
        (ROOT / "modules/llm-models/files/etc/aipc/models/models.yaml").read_text()
    )
    glm = next(item for item in models["models"] if item["alias"] == "glm-cloud")
    assert glm == {
        "alias": "glm-cloud",
        "backend": "zai",
        "model_id": "glm-5.2",
        "size_gb": "cloud",
    }

    template = (ROOT / "secrets/cloud-llm.yaml.example").read_text()
    decrypt = (
        ROOT / "modules/secrets-sops/files/usr/lib/aipc/decrypt-cloud-keys.sh"
    ).read_text()
    assert 'zai_api_key: "REPLACE_ME"' in template
    assert "Z_AI_API_KEY" in decrypt
    assert "zai_api_key" in decrypt
