# Vidra User — Design System (skeleton)

> Status: SKELETON — expand as components/tokens land. Use uploaded Vidra design docs
> as the visual source of truth when present.

## Default direction
- Apple-inspired responsive layout.
- Mobile bottom tabs; desktop/tablet sidebar.
- No hamburger menus for primary navigation.
- Semantic color tokens, not scattered hex values.
- Accessible focus rings.
- Dark mode support.
- Reduced-motion and reduced-transparency support.
- Custom components, not UI-kit wrappers.

## Tokens (to define)
- [ ] Color (semantic: surface, text, accent, danger, success, border, focus).
- [ ] Typography scale.
- [ ] Spacing / radius / elevation scale.
- [ ] Motion / easing tokens (with reduced-motion variants).

## Icons
- Minified inline SVGs or local icon wrappers (Feather-style). No icon-font deps.

## Component primitives (target)
Button, LinkButton, IconButton, Input, Textarea, Select, Checkbox, Radio, Toggle,
Modal, Dropdown, Tabs, Toast, Card, Badge, Avatar, Skeleton, EmptyState, ErrorState.

## Accessibility baseline
- ARIA labels on icon-only buttons.
- Keyboard navigation + focus management for dialogs/dropdowns.
- Responsive coverage for mobile/tablet/desktop.
