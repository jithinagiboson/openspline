import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from openspline_server.app import create_app
from openspline_server.config import Settings
from openspline_server.worker import WorkerPool, default_attention
from PIL import Image


def portrait():
    data = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(data, format="PNG")
    return data.getvalue()


def test_demo_switches_attention_in_place_and_mid_session(tmp_path):
    app = create_app(Settings(backend="test", runtime_dir=str(tmp_path)))
    with TestClient(app) as client:
        worker = app.state.pool.workers[0]
        pid = worker.process.pid
        state = client.get("/v1/demo/attention").json()
        assert state["mode"] == default_attention()
        assert set(state["kernels"]) == {"sage", "flash"}

        response = client.post("/v1/demo/attention", json={"mode": "pytorch"})
        assert response.status_code == 200 and response.json()["mode"] == "pytorch"
        # Switching never reloads the model process.
        assert worker.ready and worker.process.pid == pid and worker.attention == "pytorch"

        response = client.post(
            "/v1/sessions", data={"quality": "low"}, files={"portrait": ("p.png", portrait())}
        )
        assert response.status_code == 201, response.text
        session = response.json()
        for mode in ("sage", "flash"):
            response = client.post("/v1/demo/attention", json={"mode": mode})
            assert response.status_code == 200 and response.json()["mode"] == mode
            assert worker.ready and worker.owner == session["id"] and worker.attention == mode

        for mode in (None, "fast", 1):
            response = client.post("/v1/demo/attention", json={"mode": mode})
            assert response.status_code == 422
        assert client.get("/v1/demo/attention").json()["mode"] == "flash"


def test_restarted_worker_keeps_attention_mode(tmp_path):
    async def run():
        pool = WorkerPool(Settings(backend="test", runtime_dir=str(tmp_path)))
        await pool.start()
        try:
            await pool.set_attention("pytorch")
            worker = pool.workers[0]
            await worker.stop()
            await worker.start()
            assert worker.ready and pool.attention == "pytorch"
            await worker.call("attention", "flash")
        finally:
            await pool.close()

    asyncio.run(run())


def test_gpu_backend_rejects_kernels_that_are_not_installed(tmp_path, monkeypatch):
    from openspline_server import worker as worker_module

    monkeypatch.setattr(worker_module, "installed_attention_kernels", lambda: ["flash_attn"])
    pool = WorkerPool(Settings(backend="gpu", runtime_dir=str(tmp_path)))
    assert pool.attention == "flash"
    with pytest.raises(ValueError, match="SageAttention is not installed"):
        asyncio.run(pool.set_attention("sage"))
    asyncio.run(pool.set_attention("pytorch"))
    assert pool.attention == "pytorch"

    monkeypatch.setattr(worker_module, "installed_attention_kernels", lambda: [])
    with pytest.raises(ValueError, match="FlashAttention is not installed"):
        asyncio.run(pool.set_attention("flash"))


def test_default_attention_prefers_fastest_installed(monkeypatch):
    from openspline_server import worker as worker_module

    for installed, mode in (
        (["sageattention", "flash_attn"], "sage"),
        (["flash_attn_interface"], "flash"),
        ([], "pytorch"),
    ):
        monkeypatch.setattr(worker_module, "installed_attention_kernels", lambda i=installed: i)
        assert default_attention() == mode


def test_gpu_engine_exposes_only_the_chosen_kernels():
    from types import SimpleNamespace

    from openspline_server.worker import ATTENTION_KERNELS, GPUEngine

    engine = GPUEngine.__new__(GPUEngine)
    engine.attention_module = SimpleNamespace()
    engine.attention_kernels = dict.fromkeys(ATTENTION_KERNELS, True)
    for mode, enabled in (
        ("sage", {"SAGE_ATTN_AVAILABLE"}),
        ("flash", {"FLASH_ATTN_3_AVAILABLE", "FLASH_ATTN_2_AVAILABLE"}),
        ("pytorch", set()),
    ):
        engine.set_attention(mode)
        assert {name for name in ATTENTION_KERNELS if getattr(engine.attention_module, name)} == enabled
