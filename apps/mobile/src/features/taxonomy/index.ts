/**
 * The fashion taxonomy.
 *
 * Organised around one idea: an outfit is described along *independent* dimensions —
 * garment identity, aesthetic, dress code, occasion, environment and wearer
 * requirements — rather than filed under a single category. See `dimensions.ts` for
 * why that matters and what it rules out.
 *
 * Mirrors the shape the backend stores, so a record moves between them untranslated.
 *
 * Exports are listed explicitly rather than re-exported with `export *`: a blanket
 * re-export makes the public surface whatever the files happen to contain, and
 * silently collides when two modules name the same thing.
 */

export {
  AESTHETICS,
  SEARCH_ALIASES,
  aestheticById,
  resolveAestheticSearch,
  type Aesthetic,
  type AestheticFamily,
} from './aesthetics';

export {
  FORBIDDEN_INFERENCES,
  NOT_INFERABLE_FROM_IMAGE,
  RESOLUTION_ORDER,
  isForbiddenInference,
  type AttributeSource,
  type Attributed,
  type DimensionKind,
  type ResolutionStage,
} from './dimensions';

export {
  DRESS_CODES,
  WEAR_CONTEXTS,
  dressCodeById,
  needsClarification,
  type CoveragePreference,
  type DressCode,
  type WearContext,
} from './dress-codes';

export {
  CLASSIFICATION_LABELS,
  GARMENT_CATEGORIES,
  REGIONAL_GARMENTS,
  SLOTS,
  SLOT_LABELS,
  categoriesInSlot,
  categoryById,
  slotFor,
  type GarmentCategory,
  type RegionalGarment,
  type Slot,
} from './garments';

export {
  explainAesthetic,
  piecesBySlot,
  type OutfitPiece,
  type OutfitRecord,
} from './outfit';
