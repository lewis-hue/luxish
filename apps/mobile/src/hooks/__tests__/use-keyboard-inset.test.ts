import { composerInset } from '@/hooks/use-keyboard-inset';

describe('composerInset', () => {
  it('clears the home indicator when the keyboard is down', () => {
    expect(composerInset({ keyboard: 0, safeArea: 34 })).toBe(34);
  });

  it('sits on the keyboard when it is up', () => {
    // The keyboard covers the home indicator entirely, so adding
    // both would lift the composer a finger's width above the keys
    // for no reason.
    expect(composerInset({ keyboard: 336, safeArea: 34 })).toBe(336);
  });

  it('does not add the two together', () => {
    expect(composerInset({ keyboard: 336, safeArea: 34 })).toBeLessThan(370);
  });

  it('works on a phone with no bottom inset', () => {
    expect(composerInset({ keyboard: 0, safeArea: 0 })).toBe(0);
    expect(composerInset({ keyboard: 290, safeArea: 0 })).toBe(290);
  });
});
