# Openspline Cloud quickstart

## Option 1: avatar components (no setup required)

You can create an avatar by uploading an image, selecting a voice and defining a prompt at [openspline.dev](https://openspline.dev).
After creating the avatar you can embed the avatar in your frontend directly, no setup required.

```jsx
<script src="https://dashboard.openspline.dev/embed.js" defer></script>
<openspline-cloud
  cloud-url="https://dashboard.openspline.dev"
  path="nikola-tesla1">
</openspline-cloud>
```

or directly HTML

```html
<script src="https://dashboard.openspline.dev/embed.js" defer></script>
<openspline-cloud
  cloud-url="https://dashboard.openspline.dev"
  path="nikola-tesla1">
</openspline-cloud>
```

## Option 2: API to generate on openspline GPU

Create an API key in the [Cloud dashboard](https://dashboard.openspline.dev/developers), install `pip install openspline`, and add this to your async voice agent:

```python
from openspline import Openspline

async with Openspline(api_key="YOUR_API_KEY").avatar("portrait.jpg") as avatar:
    print(avatar.viewer_url)
    await avatar.stream(agent.audio_stream(), sample_rate=24000)
```

Open the printed viewer URL to start playback, or pass `avatar.session` to your frontend. Your agent supplies PCM16 audio; Cloud runs the avatar model.

You can pass the key as `Openspline(api_key="YOUR_API_KEY")` in Python or `new Openspline({ apiKey: "YOUR_API_KEY" })` in Node. Use `avatar(avatar_id="YOUR_AVATAR_ID")` to reuse a saved dashboard portrait and background.
