"""Real HTTP/WebSocket SDK → gateway → inference protocol, using the CPU test backend."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import socket

import httpx
from PIL import Image
import pytest
import uvicorn

from openspline import Openspline
from openspline_server.app import create_app
from openspline_server.config import Settings


async def serve(app):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    address = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='on', timeout_graceful_shutdown=1))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(100):
        if server.started: return server, task, address
        if task.done(): await task
        await asyncio.sleep(.05)
    raise TimeoutError('Test server did not start')


async def test_cloud_round_trip_native_media_interrupt_and_shutdown(tmp_path, monkeypatch):
    import time
    import openspline.client as sdk
    gateway_path = Path(__file__).resolve().parents[1] / 'experiments/openspline_cloud/modal/api_runtime.py'
    if not gateway_path.exists():
        pytest.skip('Cloud experiment is not included in this checkout')
    engine, engine_task, engine_url = await serve(create_app(Settings(backend='test', runtime_dir=str(tmp_path))))
    config = {'id': 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', 'token': 'publisher', 'deadline': int((time.time() + 660) * 1000),
              'maxSeconds': 60, 'quality': 'lite', 'imageUrl': 'https://images.invalid/portrait',
              'usageUrl': 'https://cloud.invalid/usage', 'usageToken': 'worker-only'}
    monkeypatch.setenv('CLOUD_SESSION', json.dumps(config))
    spec = importlib.util.spec_from_file_location('e2e_gateway', gateway_path)
    gateway = importlib.util.module_from_spec(spec); spec.loader.exec_module(gateway)
    gateway.LOCAL = engine_url
    image = io.BytesIO(); Image.new('RGB', (256, 256), '#668855').save(image, format='PNG')
    reports = []
    async def report(event): reports.append(event)
    async def download(*args): return image.getvalue()
    async def finish():
        if not gateway.stopping:
            gateway.stopping = True
            await report('ended')
    async def budget(ws): await asyncio.Future()
    gateway.report, gateway.download, gateway.finish, gateway.watch_budget = report, download, finish, budget
    api, api_task, api_url = await serve(gateway.app)
    gateway.origin = lambda connection: api_url
    requests = []
    async def account(request):
        requests.append(request)
        assert request.headers['authorization'] == 'Bearer account-key'
        if request.method == 'DELETE': return httpx.Response(204)
        return httpx.Response(201, json={'id': config['id'], 'url': api_url, 'publisher_token': config['token'], 'cloud': True})
    real = httpx.AsyncClient
    def client(*args, **kwargs):
        if kwargs.get('base_url') == 'https://cloud.invalid/api': kwargs['transport'] = httpx.MockTransport(account)
        return real(*args, **kwargs)
    monkeypatch.setattr(sdk.httpx, 'AsyncClient', client)
    count = {'video': 0, 'audio': 0}
    consumer = None
    try:
        async with Openspline(url='https://cloud.invalid/api', api_key='account-key', timeout=10).avatar(image.getvalue()) as avatar:
            assert avatar.session['id'] == config['id']
            assert avatar.session['transport'] == 'websocket'
            media = await avatar.media()
            async def consume():
                async for kind, frame in media:
                    count[kind] += 1
                    if kind == 'audio': media.acknowledge()
            consumer = asyncio.create_task(consume())
            await asyncio.wait_for(avatar.wait_for_viewer(), 5)
            assert reports == ['ready']
            await avatar.send_audio(bytes(24000), sample_rate=24000)
            await asyncio.wait_for(avatar.end_turn(), 10)
            assert count['video'] > 0 and count['audio'] > 0
            await avatar.interrupt()
            assert avatar.epoch == 1
        assert reports == ['ready', 'ended']
        assert requests[-1].method == 'DELETE'
    finally:
        if consumer:
            consumer.cancel(); await asyncio.gather(consumer, return_exceptions=True)
        api.should_exit = engine.should_exit = True
        await asyncio.wait_for(asyncio.gather(api_task, engine_task), 10)
