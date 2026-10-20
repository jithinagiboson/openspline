# Custom photo and video backgrounds

Pass an optional `background` file path or bytes when creating the avatar. Images stay still; videos loop silently during speech and idle playback. Upload a **PNG portrait with its background removed**: compositing uses the original portrait's alpha matte (a fixed silhouette, not automatic per-frame segmentation). Opaque portraits retain their original background. The background fills the portrait's aspect ratio with a centered cover crop.

```python
async with Openspline().avatar("portrait.png", background="scene.mp4") as avatar:
    # Use any existing audio connector with this avatar.
    await avatar.play_file("speech.wav")
```

```javascript
const avatar = await new Openspline().avatar("portrait.png", {
  background: "scene.jpg", // MP4/WebM or image; path or Uint8Array
});
```

LiveKit's Python `AvatarSession` and Node `LiveKitAvatarSession`, Pipecat's `AvatarProcessor`, and TEN's extension properties also accept `background`. OpenAI Realtime/Agents, Gemini Live, Google ADK, ElevenLabs, Vocode, and universal audio adapters use the background configured on their shared avatar session. Browser, React, web component, WebRTC, and native LiveKit viewers receive the already-composited video without extra configuration.

The HTTP API accepts an optional `background` file alongside `portrait` and `quality` in `POST /v1/sessions`. Limits: 25 MiB per background, 16 megapixels, and video up to 60 seconds / 120 fps. Video decoding retains only the current and next frame. Background selection lasts for the session; omit the field to keep the existing behavior.
