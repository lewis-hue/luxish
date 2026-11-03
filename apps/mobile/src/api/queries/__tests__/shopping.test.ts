/**
 * The two lines every shop card carries, which are the two places a
 * curated reference could quietly become a live quote.
 */

import { checkedLine, formatPrice } from '@/api/queries/shopping';

describe('formatPrice', () => {
  it('renders integer minor units as whole currency', () => {
    const rendered = formatPrice(499000, 'KES');
    expect(rendered).toContain('4,990');
    expect(rendered).not.toContain('.00');
  });

  it('never produces a float artefact', () => {
    expect(formatPrice(1, 'KES')).not.toContain('0.01');
  });
});

describe('checkedLine', () => {
  it('names the provenance and the date', () => {
    const line = checkedLine({ retrievedAt: '2026-10-30T12:00:00Z', stale: false });
    expect(line).toContain('Curated reference');
    expect(line).toContain('Oct');
    expect(line).not.toContain('out of date');
  });

  it('adds the warning once the window lapses', () => {
    const line = checkedLine({ retrievedAt: '2026-01-01T12:00:00Z', stale: true });
    expect(line).toContain('May be out of date.');
  });
});
