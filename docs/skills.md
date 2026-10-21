# OpenSpline integration instructions for agents

Read [llms.md](llms.md) for the complete product reference and runnable example links. This file is the short task guide.

## Choose a path

- User wants to try an avatar immediately: send them to `https://dashboard.openspline.dev/explore`.
- User wants a hosted avatar with no backend: use the dashboard embed in `get-started/cloud-dashboard.mdx`.
- User has a voice agent and no GPU: use a Cloud API key with the Python or Node SDK.
- User has an NVIDIA GPU: install the local service, then use the same SDK without a Cloud key.
- User has a specific voice provider: choose its connector page in `connectors/` and use the linked runnable example.

## Integration rules

1. Keep Cloud API keys, provider credentials, and publisher tokens on the server. Send only the session descriptor to a browser player.
2. Use `async with Openspline().avatar(...)` in Python. In Node, call `await avatar.close()` in `finally`.
3. Audio streaming expects the stated sample rate and encoding. Default audio is mono PCM16; close each turn with `end_turn()` when sending chunks manually.
4. Wait for the viewer before sending speech if playback should start only after a viewer connects.
5. Handle interruption in the user's agent and forward it to the avatar. Keep transcript, tool, input, and provider event handlers.
6. Validate against the repository example and installed SDK version. Do not invent unsupported methods or expose server credentials in frontend code.

## Minimal Python pattern

```python
from openspline import Openspline

async with Openspline().avatar("portrait.jpg") as avatar:
    print(avatar.viewer_url)
    await avatar.stream(agent.audio_stream(), sample_rate=24000)
```

Set `OPENSPLINE_API_KEY` for Cloud; leave it unset for the local service at `http://localhost:7860`.
