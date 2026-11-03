/**
 * The collage model.
 *
 * Undo is where editors go wrong, and the ways they go wrong are
 * specific: a redo that survives a new edit, a history that grows
 * without bound, a coordinate stored in pixels so the export does not
 * match the canvas. Each has a test.
 */

import {
  BACKGROUNDS,
  EMPTY,
  HISTORY,
  MAX_PIECES,
  backgroundColour,
  begin,
  bringForward,
  canRedo,
  canUndo,
  commit,
  place,
  redo,
  remove,
  undo,
  update,
} from '@/features/collage/model';

describe('placing pictures', () => {
  it('stores position as a fraction of the canvas, never pixels', () => {
    // The editor and the exported picture are different sizes. A
    // layout in pixels only looks right on the phone it was made on.
    const collage = place(EMPTY, 'file://a.png', 0.8);
    const piece = collage.pieces[0];
    expect(piece.x).toBeGreaterThan(0);
    expect(piece.x).toBeLessThan(1);
    expect(piece.y).toBeGreaterThan(0);
    expect(piece.y).toBeLessThan(1);
    expect(piece.width).toBeLessThanOrEqual(1);
  });

  it('keeps the picture ratio so nothing is squashed', () => {
    expect(place(EMPTY, 'file://a.png', 0.75).pieces[0].ratio).toBe(0.75);
  });

  it('falls back to square for a ratio it was not given', () => {
    expect(place(EMPTY, 'file://a.png', 0).pieces[0].ratio).toBe(1);
  });

  it('staggers new pictures so they do not hide behind each other', () => {
    let collage = EMPTY;
    for (let n = 0; n < 4; n += 1) {
      collage = place(collage, `file://${n}.png`, 1);
    }
    const spots = collage.pieces.map((piece) => `${piece.x},${piece.y}`);
    expect(new Set(spots).size).toBe(4);
  });

  it('refuses past the cap rather than growing without bound', () => {
    let collage = EMPTY;
    for (let n = 0; n < MAX_PIECES + 5; n += 1) {
      collage = place(collage, `file://${n}.png`, 1);
    }
    expect(collage.pieces).toHaveLength(MAX_PIECES);
  });

  it('puts the newest piece on top, which is what the order means', () => {
    const collage = place(place(EMPTY, 'file://a.png', 1), 'file://b.png', 1);
    expect(collage.pieces.at(-1)?.uri).toBe('file://b.png');
  });
});

describe('editing', () => {
  it('changes only the piece named', () => {
    const collage = place(place(EMPTY, 'file://a.png', 1), 'file://b.png', 1);
    const [first, second] = collage.pieces;
    const moved = update(collage, first.id, { x: 0.1 });
    expect(moved.pieces[0].x).toBe(0.1);
    expect(moved.pieces[1]).toEqual(second);
  });

  it('brings a piece to the top without losing the others', () => {
    let collage = EMPTY;
    for (const name of ['a', 'b', 'c']) {
      collage = place(collage, `file://${name}.png`, 1);
    }
    const bottom = collage.pieces[0];
    const raised = bringForward(collage, bottom.id);
    expect(raised.pieces).toHaveLength(3);
    expect(raised.pieces.at(-1)?.id).toBe(bottom.id);
  });

  it('removes one piece and leaves the rest', () => {
    const collage = place(place(EMPTY, 'file://a.png', 1), 'file://b.png', 1);
    const left = remove(collage, collage.pieces[0].id);
    expect(left.pieces).toHaveLength(1);
    expect(left.pieces[0].uri).toBe('file://b.png');
  });
});

describe('undo and redo', () => {
  it('goes back to the state before the change', () => {
    const one = commit(begin(), place(EMPTY, 'file://a.png', 1));
    expect(one.present.pieces).toHaveLength(1);
    expect(undo(one).present.pieces).toHaveLength(0);
  });

  it('redoes what was undone', () => {
    const one = commit(begin(), place(EMPTY, 'file://a.png', 1));
    expect(redo(undo(one)).present.pieces).toHaveLength(1);
  });

  it('drops the redo stack once something new is done', () => {
    // Otherwise redo resurrects a branch the person abandoned, which
    // is the single most confusing thing an editor can do.
    const one = commit(begin(), place(EMPTY, 'file://a.png', 1));
    const back = undo(one);
    expect(canRedo(back)).toBe(true);

    const other = commit(back, place(back.present, 'file://b.png', 1));
    expect(canRedo(other)).toBe(false);
    expect(other.present.pieces[0].uri).toBe('file://b.png');
  });

  it('does nothing at the ends rather than throwing', () => {
    const fresh = begin();
    expect(canUndo(fresh)).toBe(false);
    expect(undo(fresh)).toBe(fresh);
    expect(redo(fresh)).toBe(fresh);
  });

  it('bounds the history, because a long session is not a memory leak', () => {
    let session = begin();
    for (let n = 0; n < HISTORY + 10; n += 1) {
      session = commit(session, place(session.present, `file://${n}.png`, 1));
    }
    expect(session.past.length).toBeLessThanOrEqual(HISTORY);
  });

  it('ignores a commit that changed nothing', () => {
    const session = commit(begin(), place(EMPTY, 'file://a.png', 1));
    expect(commit(session, session.present)).toBe(session);
  });
});

describe('backgrounds', () => {
  it('resolves every offered background to a colour', () => {
    for (const paper of BACKGROUNDS) {
      expect(backgroundColour(paper.id)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('falls back rather than rendering a transparent canvas', () => {
    expect(backgroundColour('not-a-background')).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });
});
