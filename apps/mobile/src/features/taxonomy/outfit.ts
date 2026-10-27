import type { Aesthetic } from './aesthetics';
import type { Slot } from './garments';

/**
 * An outfit: the pieces, plus the dimensions that describe the combination.
 *
 * Aesthetics live here and not on a garment, because they are a property of the
 * combination. The same shirt is classic, business formal or streetwear depending
 * only on what it is worn with.
 */
export interface OutfitPiece {
  /** A wardrobe garment id, or a reference piece on a Discover look. */
  id: string;
  name: string;
  categoryId: string;
  slot: Slot;
  /** Where in the outfit this sits: top, bottom, outer, shoes, bag, accessory. */
  role: string;
  colour: string | null;
  /** Whether the viewing user owns this piece. Drives "find it" vs "wear it". */
  owned: boolean;
  image?: number | null;
  blurhash?: string | null;
}

export interface OutfitRecord {
  id: string;
  title: string;
  pieces: readonly OutfitPiece[];

  /** Multi-label by design — an outfit is rarely exactly one thing. */
  aesthetics: readonly string[];
  dressCode: string;
  occasions: readonly string[];

  /**
   * Why those aesthetic labels were applied. Shown to the user, because an
   * unexplained tag is not useful and cannot be argued with.
   */
  styleEvidence: readonly string[];

  /** Conditions the look assumes. Separate from the look itself. */
  environment?: readonly string[];
  /** Stated requirements this look satisfies, e.g. full-length, opaque. */
  wearerRequirements?: readonly string[];

  /** True when the imagery was generated rather than photographed. */
  isGenerated?: boolean;
}

/** Explains a label in terms a person can disagree with specifically. */
export function explainAesthetic(
  aesthetic: Aesthetic,
  evidence: readonly string[],
): string {
  const matched = evidence.filter((item) =>
    aesthetic.cues.some((cue) => item.toLowerCase().includes(cue.toLowerCase())),
  );
  const shown = matched.length ? matched : evidence.slice(0, 3);
  return shown.length
    ? `${aesthetic.label} — ${shown.join(', ')}`
    : aesthetic.label;
}

/** Groups pieces by slot for a detail view, in a stable, readable order. */
export function piecesBySlot(
  pieces: readonly OutfitPiece[],
): readonly { slot: Slot; pieces: readonly OutfitPiece[] }[] {
  const order: Slot[] = ['tops', 'bottoms', 'outerwear', 'shoes', 'accessories'];
  return order
    .map((slot) => ({ slot, pieces: pieces.filter((piece) => piece.slot === slot) }))
    .filter((group) => group.pieces.length > 0);
}

