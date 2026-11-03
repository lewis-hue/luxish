import { isOwnPage } from '@/features/profile/whose-page';

describe('isOwnPage', () => {
  it('knows your own page when you open it', () => {
    expect(isOwnPage({ viewerId: 'u1', pageId: 'u1' })).toBe(true);
  });

  it('knows somebody else', () => {
    expect(isOwnPage({ viewerId: 'u1', pageId: 'u2' })).toBe(false);
  });

  it('is false while identity is still loading', () => {
    // The member screen must not decide on a half-loaded answer: it
    // would paint the visitor's view of your own account first.
    expect(isOwnPage({ viewerId: undefined, pageId: 'u1' })).toBe(false);
  });

  it('is false when signed out', () => {
    expect(isOwnPage({ viewerId: null, pageId: 'u1' })).toBe(false);
  });

  it('never matches two blanks', () => {
    // `undefined === undefined` is true, which would have sent a
    // stranger's page to your own profile.
    expect(isOwnPage({})).toBe(false);
    expect(isOwnPage({ viewerId: undefined, pageId: undefined })).toBe(false);
    expect(isOwnPage({ viewerId: '', pageId: '' })).toBe(false);
    expect(isOwnPage({ viewerId: '  ', pageId: '  ' })).toBe(false);
  });

  it('ignores padding around an id', () => {
    expect(isOwnPage({ viewerId: 'u1', pageId: ' u1 ' })).toBe(true);
  });

  it('does not treat a different case as the same account', () => {
    // Ids here are UUIDs from the server, compared as the server
    // wrote them. Case-folding would be inventing a rule.
    expect(isOwnPage({ viewerId: 'AB', pageId: 'ab' })).toBe(false);
  });
});
