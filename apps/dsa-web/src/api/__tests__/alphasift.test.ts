import { beforeEach, describe, expect, it, vi } from 'vitest';
import { alphasiftApi } from '../alphasift';

const { get, post, getConfig, updateConfig } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
  },
}));

vi.mock('../systemConfig', () => ({
  systemConfigApi: {
    getConfig: (...args: unknown[]) => getConfig(...args),
    update: (...args: unknown[]) => updateConfig(...args),
  },
}));

describe('alphasiftApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    getConfig.mockReset();
    updateConfig.mockReset();
  });

  it('enables the config before calling install', async () => {
    getConfig.mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' });
    updateConfig.mockResolvedValueOnce({ success: true });
    post.mockResolvedValueOnce({
      data: {
        installed: true,
        already_installed: true,
        install_spec_is_default: true,
      },
    });

    await alphasiftApi.enable();

    expect(updateConfig).toHaveBeenCalledWith({
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'ALPHASIFT_ENABLED', value: 'true' }],
    });
    expect(post).toHaveBeenCalledWith('/api/v1/alphasift/install', {}, { timeout: 180000 });
    expect(updateConfig.mock.invocationCallOrder[0]).toBeLessThan(post.mock.invocationCallOrder[0]);
  });

  it('keeps enable ordering when called without object binding', async () => {
    getConfig.mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' });
    updateConfig.mockResolvedValueOnce({ success: true });
    post.mockResolvedValueOnce({
      data: {
        installed: true,
        already_installed: true,
        install_spec_is_default: true,
      },
    });

    const enable = alphasiftApi.enable;
    await enable();

    expect(updateConfig.mock.invocationCallOrder[0]).toBeLessThan(post.mock.invocationCallOrder[0]);
  });

  it('loads strategies from the AlphaSift API', async () => {
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        strategies: [{ id: 'dual_low', name: 'Dual Low', market_scope: ['cn'] }],
        strategy_count: 1,
      },
    });

    const result = await alphasiftApi.getStrategies();

    expect(get).toHaveBeenCalledWith('/api/v1/alphasift/strategies');
    expect(result.strategies[0].id).toBe('dual_low');
    expect(result.strategies[0].marketScope).toEqual(['cn']);
  });

  it('uses a long timeout for LLM-backed screening', async () => {
    post.mockResolvedValueOnce({
      data: {
        enabled: true,
        candidates: [],
        candidate_count: 0,
        llm_ranked: true,
      },
    });

    await alphasiftApi.screen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/alphasift/screen',
      { market: 'cn', strategy: 'dual_low', max_results: 3 },
      { timeout: 180000 }
    );
  });
});
