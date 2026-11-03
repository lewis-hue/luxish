/**
 * The meter sentence, which is the one piece of billing copy assembled on
 * the device and therefore the one place a plural or a date can go wrong
 * where no server test would see it.
 */

import { meterLine, shortDate } from '@/api/queries/billing';

describe('meterLine', () => {
  it('says where the count stands and when it resets', () => {
    const line = meterLine({ remaining: 9, allowance: 12, resetsAt: '2026-12-01T00:00:00Z' });
    // The date half is rendered in the device's locale, so the test pins
    // the facts rather than one locale's ordering of them.
    expect(line).toMatch(/^9 of 12 stylist runs left this month\. Resets /);
    expect(line).toContain('December');
    expect(line).toContain('1');
  });

  it('handles the singular allowance without saying "1 runs"', () => {
    expect(
      meterLine({ remaining: 0, allowance: 1, resetsAt: '2026-12-01T00:00:00Z' }),
    ).toContain('stylist run left');
  });
});

describe('shortDate', () => {
  it('renders a day and month in the device locale', () => {
    const rendered = shortDate('2026-12-01T00:00:00Z');
    expect(rendered).toContain('December');
    expect(rendered).toContain('1');
  });

  it('answers nothing for nothing', () => {
    expect(shortDate(null)).toBe('');
    expect(shortDate('garbage')).toBe('');
  });
});
