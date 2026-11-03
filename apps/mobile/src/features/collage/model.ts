/**
 * What a collage is, and what can be done to it.
 *
 * **A list of placed pictures, in order.** Position, scale and
 * rotation per piece, and the order *is* the stacking: the last item
 * is on top. Anything more structured - groups, frames, masks - is a
 * feature nobody has asked for carrying a data model everything else
 * would have to understand.
 *
 * **Every change is a whole new state.** Undo is then a list of
 * states rather than a list of inverse operations, which is the
 * difference between "undo works" and "undo works except after a
 * rotate followed by a delete". A collage is a handful of small
 * objects; copying it costs nothing worth optimising.
 *
 * **Coordinates are fractions of the canvas, not pixels.** The editor
 * and the exported picture are different sizes, and a layout stored in
 * pixels would be a layout that only looks right on the phone it was
 * made on.
 */

/** One picture placed on the canvas. */
export interface Piece {
  id: string;
  /** A local file URI. Everything on a canvas is already on the device. */
  uri: string;
  /** Centre, as a fraction of the canvas: 0.5, 0.5 is the middle. */
  x: number;
  y: number;
  /** Width as a fraction of the canvas width. Height follows the ratio. */
  width: number;
  /** The picture's own aspect, so it is never squashed. */
  ratio: number;
  /** Radians. */
  rotation: number;
}

export interface Collage {
  pieces: Piece[];
  /** The paper behind everything, as a colour token name. */
  background: string;
}

export const EMPTY: Collage = { pieces: [], background: 'paper' };

/** The backgrounds on offer. Few, and all of them quiet. */
export const BACKGROUNDS: readonly { id: string; label: string; colour: string }[] =
  [
    { id: 'paper', label: 'Paper', colour: '#FAF7F2' },
    { id: 'bone', label: 'Bone', colour: '#EDE7DD' },
    { id: 'slate', label: 'Slate', colour: '#2C2C2E' },
    { id: 'ink', label: 'Ink', colour: '#121212' },
    { id: 'blush', label: 'Blush', colour: '#F0DEDC' },
    { id: 'moss', label: 'Moss', colour: '#DDE3D5' },
  ];

export function backgroundColour(id: string): string {
  return BACKGROUNDS.find((b) => b.id === id)?.colour ?? '#FAF7F2';
}

/** The most pieces one collage may hold. */
export const MAX_PIECES = 20;

/**
 * Where a new piece lands.
 *
 * Near the middle but not exactly on it, and stepped by how many are
 * already there, so adding five in a row produces a stack somebody can
 * see and grab rather than five pictures hiding behind each other.
 */
export function place(collage: Collage, uri: string, ratio: number): Collage {
  if (collage.pieces.length >= MAX_PIECES) return collage;
  const step = collage.pieces.length % 6;
  return {
    ...collage,
    pieces: [
      ...collage.pieces,
      {
        id: `${Date.now()}-${collage.pieces.length}`,
        uri,
        x: 0.5 + (step - 2.5) * 0.04,
        y: 0.5 + (step - 2.5) * 0.04,
        width: 0.45,
        ratio: ratio > 0 ? ratio : 1,
        rotation: 0,
      },
    ],
  };
}

export function update(collage: Collage, id: string, patch: Partial<Piece>): Collage {
  return {
    ...collage,
    pieces: collage.pieces.map((piece) =>
      piece.id === id ? { ...piece, ...patch } : piece,
    ),
  };
}

export function remove(collage: Collage, id: string): Collage {
  return { ...collage, pieces: collage.pieces.filter((piece) => piece.id !== id) };
}

/** Move a piece to the top of the stack, which is what selecting means. */
export function bringForward(collage: Collage, id: string): Collage {
  const piece = collage.pieces.find((p) => p.id === id);
  if (!piece) return collage;
  return {
    ...collage,
    pieces: [...collage.pieces.filter((p) => p.id !== id), piece],
  };
}

/**
 * The undo stack.
 *
 * Bounded, because a collage session can run for a long time and an
 * unbounded history of whole states is a memory leak with a friendly
 * name. Twenty steps is further back than anybody reaches.
 */
export const HISTORY = 20;

export interface Session {
  past: Collage[];
  present: Collage;
  future: Collage[];
}

export function begin(collage: Collage = EMPTY): Session {
  return { past: [], present: collage, future: [] };
}

/** Record a change. Anything undone is dropped, as everywhere. */
export function commit(session: Session, next: Collage): Session {
  if (next === session.present) return session;
  return {
    past: [...session.past, session.present].slice(-HISTORY),
    present: next,
    future: [],
  };
}

export function undo(session: Session): Session {
  const previous = session.past.at(-1);
  if (previous === undefined) return session;
  return {
    past: session.past.slice(0, -1),
    present: previous,
    future: [session.present, ...session.future].slice(0, HISTORY),
  };
}

export function redo(session: Session): Session {
  const next = session.future[0];
  if (next === undefined) return session;
  return {
    past: [...session.past, session.present].slice(-HISTORY),
    present: next,
    future: session.future.slice(1),
  };
}

export function canUndo(session: Session): boolean {
  return session.past.length > 0;
}

export function canRedo(session: Session): boolean {
  return session.future.length > 0;
}
