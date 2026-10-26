/**
 * CSS Modules are resolved by Metro on web but have no TypeScript types, so the
 * template's `animated-icon.web.tsx` import was a standing type error. Declaring
 * the shape here fixes it without a build-step change.
 */
declare module '*.module.css' {
  const classes: Record<string, string>;
  export default classes;
}

/** Side-effect-only global stylesheet import (`import '@/global.css'`). */
declare module '*.css';
