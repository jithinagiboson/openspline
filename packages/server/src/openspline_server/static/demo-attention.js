const LABELS = {sage: 'SageAttention', flash: 'FlashAttention'};

export async function setupAttentionPicker(request, select, hint) {
  let state;
  function render() {
    const installed = Object.keys(LABELS).filter(mode => state.kernels[mode].length > 0);
    for (const mode of Object.keys(LABELS)) {
      select.querySelector(`option[value="${mode}"]`).disabled = !installed.includes(mode);
    }
    select.value = installed.includes(state.mode) ? state.mode : 'pytorch';
    select.disabled = installed.length === 0;
    const kernels = state.kernels[select.value];
    hint.textContent = installed.length > 0
      ? `${kernels ? `Using ${kernels[0]}` : 'Using PyTorch attention'}. Applies immediately, even mid-session.`
      : 'SageAttention and FlashAttention are not installed; using PyTorch attention.';
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
