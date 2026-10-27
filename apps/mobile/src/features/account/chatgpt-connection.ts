/**
 * The ChatGPT connection eligibility state machine (§4), client half.
 *
 * Two facts shape this and are worth stating where the copy lives:
 *
 * 1. Identity and inference are **separate permissions**. Being signed in with
 *    ChatGPT never implies the app may spend the user's plan. The states below keep
 *    them apart, and `identity_connected` is a terminal-looking state on purpose.
 *
 * 2. There is **no API that reports remaining allowance**. Exhaustion is only
 *    observable from a `429 subscription_sharing_usage_limit_exceeded`, which can
 *    also arrive mid-stream. So `allowance_exhausted` is entered from an error, and
 *    this module must never claim a remaining quota it cannot know.
 *
 * Verified 2026-10-26 against developers.openai.com/siwc/* and
 * learn.chatgpt.com/docs/sign-in-with-chatgpt. See ADR-008.
 */

export type ChatGptConnectionState =
  /** Not offered in this build — no registered client, or not approved. */
  | 'unavailable'
  /** We have applied for commercial access and are waiting. */
  | 'approval_pending'
  /** Available, user has not connected. */
  | 'disconnected'
  /** Signed in. Identity only — grants no inference. */
  | 'identity_connected'
  /** The plan-usage scope was granted; eligible requests may use their plan. */
  | 'inference_authorized'
  /** Their plan limit is reached. Entered from a 429, never from polling. */
  | 'allowance_exhausted'
  /** The user disconnected us, or a refresh confirmed revocation. */
  | 'revoked'
  /** Transport or configuration failure. Distinct from revoked — do not clear tokens. */
  | 'error';

export interface StateCopy {
  /** Value shown on the settings row. */
  short: string;
  /** One or two sentences the user can act on. */
  detail: string;
  /** Whether a connect/retry affordance should be offered. */
  action: 'none' | 'connect' | 'reconnect' | 'retry' | 'manage_usage';
}

export const CHATGPT_STATE_COPY: Record<ChatGptConnectionState, StateCopy> = {
  unavailable: {
    short: 'Not available',
    detail:
      'Connecting a ChatGPT plan is not available in this build. Access for commercial apps is granted by OpenAI on request, and we have not been approved. Everything else in the app works without it.',
    action: 'none',
  },
  approval_pending: {
    short: 'Awaiting approval',
    detail:
      'We have asked OpenAI for access and are waiting. Nothing is required from you, and your AI allowance is unaffected.',
    action: 'none',
  },
  disconnected: {
    short: 'Not connected',
    detail:
      'You can sign in with ChatGPT to identify yourself. Using your ChatGPT plan to pay for AI requests is a separate permission you would approve on its own.',
    action: 'connect',
  },
  identity_connected: {
    short: 'Signed in only',
    detail:
      'Your ChatGPT account identifies you. It does not pay for AI requests and gives us no access to your ChatGPT conversations. Requests use your allowance in this app.',
    action: 'connect',
  },
  inference_authorized: {
    short: 'Plan connected',
    detail:
      'Eligible requests can use your ChatGPT plan. Image generation always uses this app’s own provider, because the ChatGPT plan route does not support it. You can cap or revoke this in ChatGPT settings at any time.',
    action: 'manage_usage',
  },
  allowance_exhausted: {
    short: 'Plan limit reached',
    detail:
      'Your ChatGPT plan usage for this app is used up. ' +
      'Raise the limit in ChatGPT settings, or switch to this app’s allowance.',
    action: 'manage_usage',
  },
  revoked: {
    short: 'Disconnected',
    detail:
      'Access was withdrawn, either by you in ChatGPT settings or because the connection expired. Reconnect to use it again.',
    action: 'reconnect',
  },
  error: {
    short: 'Connection problem',
    detail:
      'We could not reach ChatGPT. This is usually temporary and your connection has been kept, not cleared.',
    action: 'retry',
  },
};

/** States in which a request may be billed to the user's ChatGPT plan. */
export function canUsePlanInference(state: ChatGptConnectionState): boolean {
  return state === 'inference_authorized';
}

/**
 * Image generation is unsupported on the ChatGPT-plan route in every state, so this
 * is a constant rather than a predicate over state. Kept as a function so call sites
 * read as a check and cannot drift into assuming parity between providers.
 */
export function canUsePlanForImageGeneration(): false {
  return false;
}
