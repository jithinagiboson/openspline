"""Optional native media receiver for framework output adapters."""

import asyncio
import base64
import contextlib
import json
from fractions import Fraction

from .errors import ConnectionError


def MediaReceiver(avatar):
    return SocketMediaReceiver(avatar) if avatar.session.get("transport") == "websocket" else WebRTCMediaReceiver(avatar)


class WebRTCMediaReceiver:
    def __init__(self, avatar):
        from aiortc import RTCPeerConnection
        self.avatar = avatar
        self.pc = RTCPeerConnection()
        self.frames = asyncio.Queue(100)
        self.tasks = set()
        self.clock = None

    async def start(self):
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
        response = await self.avatar.http.get(
            f"/v1/sessions/{self.avatar.id}/ice",
            headers={"Authorization": "Bearer " + self.avatar.session["token"]},
        )
        self.avatar._check(response)
        await self.pc.close()

        self.pc = RTCPeerConnection(
            RTCConfiguration(iceServers=[RTCIceServer(**s) for s in response.json()["iceServers"]])
        )
        self.pc.addTransceiver("audio", direction="recvonly")
        self.pc.addTransceiver("video", direction="recvonly")
        self.channel = self.pc.createDataChannel("openspline")

        @self.channel.on("open")
        def opened():
            self.channel.send(json.dumps({"type": "ready"}))

        @self.channel.on("message")
        def message(raw):
            event = json.loads(raw)
            if event["type"] == "clock":
                self.clock = event
            if event["type"] == "interrupted":
                self.clock = None
                while not self.frames.empty():
                    self.frames.get_nowait()

        @self.pc.on("track")
        def track(track):
            async def receive():
                while True:
                    frame = await track.recv()
                    await self.frames.put((track.kind, frame))

            task = asyncio.create_task(receive())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        await self.pc.setLocalDescription(await self.pc.createOffer())
        s = self.avatar.session
        response = await self.avatar.http.post(
            f"/v1/sessions/{self.avatar.id}/offer",
            headers={"Authorization": "Bearer " + s["token"]},
            json={"type": self.pc.localDescription.type, "sdp": self.pc.localDescription.sdp},
        )
        self.avatar._check(response)
        await self.pc.setRemoteDescription(RTCSessionDescription(**response.json()))

    def acknowledge(self):
        if self.clock and self.channel.readyState == "open":
            self.channel.send(
                json.dumps(
                    {
                        "type": "played",
                        "epoch": self.clock["epoch"],
                        "samples": self.clock["samples"],
                    }
                )
            )

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.frames.get()

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.pc.close()



class SocketMediaReceiver:
    """Decode Cloud playback without inbound UDP. Acknowledge after consumption."""

    def __init__(self, avatar):
        self.avatar = avatar
        self.frames = asyncio.Queue(64)
        self.ws = None
        self.reader = None
        self.heartbeat = None
        self.tasks = set()
        self.epoch = 0
        self.clock = None
        self.idle_ack = None
        self.closed = False
        self.failure = None
        self.position = 0

    async def start(self):
        import av
        from websockets.legacy.client import connect

        self.decoder = av.CodecContext.create("mjpeg", "r")
        session = self.avatar.session
        self.ws = await connect(session["url"].replace("https://", "wss://").replace("http://", "ws://") +
                                f"/v1/sessions/{session['id']}/playback", max_size=4 * 1024 * 1024, open_timeout=30)
        await self.ws.send(json.dumps({"token": session["token"]}))
        self.reader = asyncio.create_task(self._receive())
        await self.ws.send(json.dumps({"type": "ready"}))
        self.heartbeat = asyncio.create_task(self._heartbeat())

    async def _heartbeat(self):
        while not self.closed:
            await asyncio.sleep(15)
            await self.ws.send(json.dumps({"type": "ping"}))

    async def _receive(self):
        import av

        try:
            async for raw in self.ws:
                event = json.loads(raw)
                epoch = event.get("epoch", self.epoch)
                if epoch < self.epoch:
                    continue
                if epoch > self.epoch or event.get("type") == "interrupted":
                    self.epoch = epoch
                    self.clock = self.idle_ack = None
                    while not self.frames.empty():
                        self.frames.get_nowait()
                kind = event.get("type")
                if kind not in {"media", "idle"}:
                    continue
                image = base64.b64decode(event["image"], validate=True)
                pictures = self.decoder.decode(av.Packet(image))
                for picture in pictures:
                    picture.pts, picture.time_base = self.position, Fraction(1, 48000)
                    idle = {"type": "idle_played", "sequence": event["sequence"], "epoch": epoch} if kind == "idle" else None
                    await self.frames.put(("video", picture, epoch, idle))
                if kind == "media":
                    data = base64.b64decode(event["audio"], validate=True)
                    if len(data) % 2 or len(data) > 3840:
                        raise ValueError("Invalid PCM frame")
                    if data:
                        frame = av.AudioFrame(format="s16", layout="mono", samples=len(data) // 2)
                        frame.planes[0].update(data)
                        frame.sample_rate = 48000
                        frame.pts, frame.time_base = self.position, Fraction(1, 48000)
                        await self.frames.put(("audio", frame, epoch, {"type": "played", "samples": event["samples"], "epoch": epoch}))
                self.position += 1920
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failure = ConnectionError("Cloud playback connection failed", "connection")
        finally:
            self.closed = True
            if self.heartbeat:
                self.heartbeat.cancel()
            # Wake a blocked iterator even when the remote closes mid-stream.
            if self.frames.full():
                self.frames.get_nowait()
            self.frames.put_nowait(None)

    def acknowledge(self):
        if self.clock and not self.closed:
            task = asyncio.create_task(self._send(self.clock))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _send(self, event):
        with contextlib.suppress(Exception):
            await self.ws.send(json.dumps(event))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idle_ack:
            await self._send(self.idle_ack)
            self.idle_ack = None
        while True:
            if self.closed and self.frames.empty():
                if self.failure:
                    raise self.failure
                raise StopAsyncIteration
            item = await self.frames.get()
            if item is None:
                if self.failure:
                    raise self.failure
                raise StopAsyncIteration
            kind, frame, epoch, feedback = item
            if epoch != self.epoch or epoch < getattr(self.avatar, "epoch", 0):
                continue
            if kind == "audio":
                self.clock = feedback
            else:
                self.idle_ack = feedback
            return kind, frame

    async def close(self):
        self.closed = True
        for task in [self.reader, self.heartbeat, *self.tasks]:
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in [self.reader, self.heartbeat, *self.tasks] if task), return_exceptions=True)
        if self.ws:
            await self.ws.close()
