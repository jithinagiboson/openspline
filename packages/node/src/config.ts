export type Quality = 'low' | 'high';

/** Client settings. Timeout values are milliseconds. */
export interface OpensplineConfig {
  url?: string;
  quality?: Quality;
  timeout?: number;
  viewerTimeout?: number;
  apiKey?: string;
}

export function resolveConfig(options: OpensplineConfig): Readonly<Required<OpensplineConfig>> {
  const allowed = new Set(['url', 'quality', 'timeout', 'viewerTimeout', 'apiKey']);
  for (const key of Object.keys(options)) {
    if (!allowed.has(key)) throw new TypeError(`Unknown openspline config field: ${key}`);
    if ((options as Record<string, unknown>)[key] === null) throw new TypeError(`${key} cannot be null`);
  }
  const apiKey = options.apiKey ?? process.env.OPENSPLINE_API_KEY ?? '';
  if (typeof apiKey !== 'string' || /\s/.test(apiKey) || (options.apiKey !== undefined && !apiKey)) throw new TypeError('apiKey must be a nonempty API key without whitespace');
  const config = {
    url: options.url ?? process.env.OPENSPLINE_URL ?? (apiKey ? 'https://dashboard.openspline.dev/api' : 'http://localhost:7860'),
    quality: options.quality ?? 'low',
    timeout: options.timeout ?? 180000,
    viewerTimeout: options.viewerTimeout ?? 60000,
    apiKey,
  };
  let url: URL;
  try { url = new URL(config.url); }
  catch { throw new TypeError('url must be an HTTP or HTTPS URL'); }
  if (typeof config.url !== 'string' || !/^https?:\/\//.test(config.url) || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.port === '0' || /\s/.test(config.url)) {
    throw new TypeError('url must be an HTTP or HTTPS URL without credentials, query, or fragment');
  }
  if (!['low', 'high'].includes(config.quality)) throw new TypeError('quality must be low or high');
  if (apiKey && url.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) throw new TypeError('Cloud API keys require HTTPS except on localhost');
  for (const name of ['timeout', 'viewerTimeout'] as const) {
    if (typeof config[name] !== 'number' || !Number.isFinite(config[name]) || config[name] <= 0 || config[name] > 2147483647 || !Number.isInteger(config[name])) {
      throw new TypeError(`${name} must be a positive integer of milliseconds (at most 2147483647)`);
    }
  }
  config.url = config.url.replace(/\/+$/, '');
  Object.defineProperty(config, 'apiKey', { value: apiKey, enumerable: false, writable: false });
  return Object.freeze(config);
}
