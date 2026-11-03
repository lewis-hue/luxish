import { StylistPanel } from '@/features/stylist/panel';

/**
 * The stylist on a screen of its own.
 *
 * **Not where people are meant to find it.** It lives on the wardrobe
 * page, above the clothes it reasons about, and that is the only
 * entry point the app offers. This route stays because things outside
 * the app point at it: a garment sheet opens `/stylist?garment=…`, a
 * fit opens `/stylist?fit=…`, and a link somebody saved should not
 * land on nothing.
 */
export default function StylistScreen() {
  return <StylistPanel />;
}
