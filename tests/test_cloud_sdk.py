import asyncio
import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from websockets.legacy.server import serve

from openspline import Openspline, OpensplineConfig
from openspline.media import SocketMediaReceiver
import openspline.client as client_module


def test_cloud_config_and_avatar_source(monkeypatch):
    monkeypatch.delenv('OPENSPLINE_URL', raising=False)
    monkeypatch.setenv('OPENSPLINE_API_KEY', 'account-secret')
    assert Openspline().url == 'https://dashboard.openspline.dev/api'
    assert 'account-secret' not in repr(OpensplineConfig())
    assert Openspline(config=OpensplineConfig(quality='high')).avatar(avatar_id='saved').avatar_id == 'saved'
    with pytest.raises(ValueError):
        Openspline().avatar('portrait', avatar_id='saved')
    monkeypatch.delenv('OPENSPLINE_API_KEY')
    assert Openspline().url == 'http://localhost:7860'
    with pytest.raises(ValueError):
        Openspline().avatar(avatar_id='saved')


async def test_cloud_sdk_handshake_control_auth_and_cleanup(monkeypatch):
    requests, events = [], []
    async def websocket(ws, path):
        assert json.loads(await ws.recv()) == {'token': 'publisher-secret'}
        await ws.send(json.dumps({'type': 'session', 'session': {
            'id': 'cloud-id', 'url': base, 'token': 'viewer-only', 'viewer_url': base + '/view#safe',
            'transport': 'websocket', 'usageToken': 'never-public',
        }}))
        await ws.send(json.dumps({'type': 'viewer_ready'}))
        async for raw in ws:
            event = json.loads(raw); events.append(event)
            await ws.send(json.dumps({'type': 'ack', 'id': event['id']}))
    async with serve(websocket, '127.0.0.1', 0) as server:
        base = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        async def http(request):
            requests.append((str(request.url), request.headers.get('authorization'), await request.aread()))
            if request.method == 'DELETE': return httpx.Response(204)
            if request.url.path.endswith('/interrupt'): return httpx.Response(200, json={'epoch': 1})
            return httpx.Response(201, json={'id': 'cloud-id', 'url': base, 'publisher_token': 'publisher-secret', 'cloud': True})
        real_client = httpx.AsyncClient
        monkeypatch.setattr(client_module.httpx, 'AsyncClient', lambda *args, **kwargs: real_client(*args, **kwargs, transport=httpx.MockTransport(http)))
        client = Openspline(api_key='account-secret', url='https://cloud.invalid/api')
        async with client.avatar(avatar_id='saved', quality='high') as avatar:
            assert avatar.session['transport'] == 'websocket'
            assert 'usageToken' not in avatar.session
            await avatar.send_audio(bytes(4800))
            await avatar.end_turn()
            await avatar.interrupt()
            assert avatar.epoch == 1
        assert b'saved' in requests[0][2]
        assert b'high' in requests[0][2]
        for url, token, _ in requests:
            assert token == ('Bearer account-secret' if url.startswith('https://cloud.invalid/') else 'Bearer publisher-secret')
        assert events[0]['type'] == 'audio'
        assert requests[-1][0] == 'https://cloud.invalid/api/v1/sessions/cloud-id'


async def test_native_socket_frames_are_synchronized_and_acknowledged_after_consumption():
    output = io.BytesIO(); Image.new('RGB', (16, 16), '#55aa77').save(output, format='JPEG')
    picture = base64.b64encode(output.getvalue()).decode()
    feedback = []; acknowledged = asyncio.Event()
    async def websocket(ws, path):
        assert json.loads(await ws.recv()) == {'token': 'viewer-only'}
        assert json.loads(await ws.recv()) == {'type': 'ready'}
        await ws.send(json.dumps({'type': 'media', 'epoch': 0, 'samples': 1920, 'audio': base64.b64encode(bytes(3840)).decode(), 'image': picture}))
        await ws.send(json.dumps({'type': 'idle', 'epoch': 0, 'sequence': 1, 'image': picture}))
        async for raw in ws:
            feedback.append(json.loads(raw))
            if feedback[-1]['type'] == 'idle_played': acknowledged.set()
    async with serve(websocket, '127.0.0.1', 0) as server:
        base = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        receiver = SocketMediaReceiver(SimpleNamespace(session={'id': 's', 'url': base, 'token': 'viewer-only'}))
        try:
            await receiver.start()
            kind, picture = await asyncio.wait_for(anext(receiver), 2); assert kind == 'video'
            kind, audio = await asyncio.wait_for(anext(receiver), 2); assert kind == 'audio'
            assert picture.pts * picture.time_base == audio.pts * audio.time_base
            assert audio.sample_rate == 48000 and audio.samples == 1920
            assert feedback == []
            receiver.acknowledge()
            kind, idle = await asyncio.wait_for(anext(receiver), 2); assert kind == 'video' and idle.pts > picture.pts
            pending = asyncio.create_task(anext(receiver))
            await asyncio.wait_for(acknowledged.wait(), 2)
            assert feedback[0] == {'type': 'played', 'samples': 1920, 'epoch': 0}
            await receiver.close()
            with pytest.raises(StopAsyncIteration): await asyncio.wait_for(pending, 2)
        finally:
            await receiver.close()
