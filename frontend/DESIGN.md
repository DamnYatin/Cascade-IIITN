# DESIGN.md — The 72-Hour Warning Design System

## Visual Identity: Emergency Operations Center (EOC)
Warm ivory/cream canvas, deep navy operational panels, bold black typography, restrained golden-yellow marker highlights, thin warm borders, and small controlled radii. Technical, calm, information-dense command-center atmosphere.
**Anti-references:** neon purple SaaS, liquid glassmorphism, rainbow gradients, decorative orbs, sparkle accents, generic admin templates.

## Palette & Design Tokens
- **Background**: `#f5f2e8` (warm ivory/cream canvas)
- **Surface (Card Cream)**: `#f8f6ef`
- **Surface Muted**: `#eee9da`
- **Navy Operational Surface**: `#10224a`
- **Navy Deep**: `#0b1737`
- **Navy Card**: `#0c1a3b`
- **Accent Gold**: `#f4c52f` (marker highlight stroke, restrained command accents)
- **Accent Gold Soft**: `#f9df72`
- **Text Primary**: `#08090c` (high contrast black on ivory)
- **Text Secondary**: `#41434a`
- **Text Muted**: `#636159` (darkened to strictly exceed WCAG AA 4.5:1 on ivory canvas)
- **Text Navy Muted**: `#8b9bb4` (for secondary labels on navy surfaces)
- **Border**: `#c9c1ab`
- **Border Subtle**: `#ded8c9`
- **Border Dark**: `#233257`

## Semantic Risk-State Tokens
Accessibility rule: Risk state is never communicated by color alone. Every risk state pairs a dedicated color, badge border, icon, and uppercase text label:
- **NORMAL**: `#42b883` | Icon: `ShieldCheck` | Label: `NORMAL`
- **WATCH**: `#64cbe3` | Icon: `Eye` | Label: `WATCH`
- **HIGH_RISK**: `#e8bd45` | Icon: `AlertTriangle` | Label: `HIGH RISK`
- **CRITICAL**: `#f17d75` | Icon: `AlertOctagon` | Label: `CRITICAL`
- **NO FORECAST / UNKNOWN**: `#636159` / `#ded8c9` | Icon: `HelpCircle` | Label: `NO FORECAST` (unknown risk is never defaulted or counted as NORMAL)

## Typography
- **Headings & Titles**: Space Grotesk (`font-heading`)
- **Body & Controls**: Inter (`font-sans`)
- **Metadata, Timestamps, Streams**: JetBrains Mono (`font-mono`, `tabular-nums`)

## Motion & Transitions
- Micro-transitions: 150ms – 250ms ease-out
- Respects `prefers-reduced-motion` with instant/opacity-only transitions
- Batched WebSocket updates to prevent UI jitter

