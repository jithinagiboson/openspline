export async function setupAttentionPicker(request, select, hint) {
  const flash = select.querySelector('option[value="flash"]');
  let state;
  function render() {
    const installed = state.kernels.length > 0;
    flash.disabled = !installed;
    select.value = installed ? state.mode : 'pytorch';
    select.disabled = !installed;
    hint.textContent = installed
      ? `${select.value === 'flash' ? `Using ${state.kernels[0]}` : 'Using PyTorch attention'}. Applies immediately, even mid-session.`
      : 'FlashAttention is not installed; using PyTorch attention.';
  }
  select.addEventListener('change', async () => {
    const mode = select.value;
    select.disabled = true;
    hint.textContent = 'Switching attention…';
    try {
      state = await request('/v1/demo/attention', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode}),
      });
      render();
    } catch (error) {
      render();
      hint.textContent = error.message;
    }
  });
  try {
    state = await request('/v1/demo/attention');
    render();
  } catch {
    select.disabled = true;
    hint.textContent = 'Attention settings are unavailable.';
  }
}
