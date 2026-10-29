import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from openspline_server.app import create_app
from openspline_server.config import Settings
from openspline_server.worker import WorkerPool
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
        assert state["mode"] == "flash" and isinstance(state["kernels"], list)

        response = client.post("/v1/demo/attention", json={"mode": "pytorch"})
        assert response.status_code == 200 and response.json()["mode"] == "pytorch"
        # Switching never reloads the model process.
        assert worker.ready and worker.process.pid == pid and worker.attention == "pytorch"

        response = client.post(
            "/v1/sessions", data={"quality": "low"}, files={"portrait": ("p.png", portrait())}
        )
        assert response.status_code == 201, response.text
        session = response.json()
        response = client.post("/v1/demo/attention", json={"mode": "flash"})
        assert response.status_code == 200 and response.json()["mode"] == "flash"
        assert worker.ready and worker.owner == session["id"] and worker.attention == "flash"

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


def test_gpu_backend_rejects_flash_without_kernels(tmp_path, monkeypatch):
    from openspline_server import worker as worker_module

    monkeypatch.setattr(worker_module, "installed_attention_kernels", lambda: [])
    pool = WorkerPool(Settings(backend="gpu", runtime_dir=str(tmp_path)))
    with pytest.raises(ValueError, match="No optimized attention kernel"):
        asyncio.run(pool.set_attention("flash"))
    asyncio.run(pool.set_attention("pytorch"))
    assert pool.attention == "pytorch"
