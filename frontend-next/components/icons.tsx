/**
 * The app's glyphs, inline.
 *
 * No icon package: this box installs nothing it does not need, the set is small
 * and fixed, and an inline path inherits `currentColor` — which is what lets a
 * skill's badge, bar and chart all take their colour from the same token.
 *
 * All icons are 24x24, stroked, so they sit on the same optical weight.
 */

type IconProps = { className?: string; size?: number };

function Svg({ children, className, size = 18 }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  );
}

export const Icon = {
  home: (p: IconProps) => (
    <Svg {...p}>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V21h14V9.5" />
    </Svg>
  ),
  mic: (p: IconProps) => (
    <Svg {...p}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </Svg>
  ),
  book: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H19v18H5.5A1.5 1.5 0 0 1 4 19.5z" />
      <path d="M8 3v18" />
    </Svg>
  ),
  chat: (p: IconProps) => (
    <Svg {...p}>
      <path d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z" />
    </Svg>
  ),
  chart: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 20V10" />
      <path d="M10 20V4" />
      <path d="M16 20v-7" />
      <path d="M22 20H2" />
    </Svg>
  ),
  report: (p: IconProps) => (
    <Svg {...p}>
      <path d="M14 3H6v18h12V7z" />
      <path d="M14 3v4h4" />
      <path d="M9 13h6M9 17h4" />
    </Svg>
  ),
  gauge: (p: IconProps) => (
    <Svg {...p}>
      <path d="M12 14 16 9" />
      <path d="M4 18a9 9 0 1 1 16 0" />
    </Svg>
  ),
  shield: (p: IconProps) => (
    <Svg {...p}>
      <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" />
    </Svg>
  ),
  settings: (p: IconProps) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1" />
    </Svg>
  ),
  flame: (p: IconProps) => (
    <Svg {...p}>
      <path d="M12 3c1 3-1.5 4-1.5 6.5A3.5 3.5 0 0 0 14 13c0-2 .5-3 .5-3 1.5 1.5 2.5 3.2 2.5 5a5 5 0 0 1-10 0c0-4 5-7 5-12z" />
    </Svg>
  ),
  trophy: (p: IconProps) => (
    <Svg {...p}>
      <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
      <path d="M8 5H5v2a3 3 0 0 0 3 3M16 5h3v2a3 3 0 0 1-3 3" />
      <path d="M10 15h4M9 20h6M12 13v7" />
    </Svg>
  ),
  spark: (p: IconProps) => (
    <Svg {...p}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6 8.4 8.4M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8" />
    </Svg>
  ),
  clock: (p: IconProps) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Svg>
  ),
  check: (p: IconProps) => (
    <Svg {...p}>
      <path d="m4 12.5 5 5L20 6.5" />
    </Svg>
  ),
  arrow: (p: IconProps) => (
    <Svg {...p}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Svg>
  ),
  play: (p: IconProps) => (
    <Svg {...p}>
      <path d="M7 4.5 19 12 7 19.5z" />
    </Svg>
  ),
  quote: (p: IconProps) => (
    <Svg {...p}>
      <path d="M9 7c-2.5 0-4 2-4 4.5S6.5 16 9 16c0-3-1-4-1-4h1zM19 7c-2.5 0-4 2-4 4.5S16.5 16 19 16c0-3-1-4-1-4h1z" />
    </Svg>
  ),
  ear: (p: IconProps) => (
    <Svg {...p}>
      <path d="M7 9a5 5 0 0 1 10 0c0 3-3 3.5-3 6a2.5 2.5 0 0 1-5 .3" />
      <path d="M10 9a2 2 0 0 1 4 0" />
    </Svg>
  ),
  pen: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 20h4L20 8l-4-4L4 16z" />
    </Svg>
  ),
  words: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 7h16M4 12h10M4 17h13" />
    </Svg>
  ),
  wave: (p: IconProps) => (
    <Svg {...p}>
      <path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2M21 12h1" />
    </Svg>
  ),
};

/** The glyph that belongs to each scored skill. */
export const SKILL_ICON: Record<string, (p: IconProps) => React.JSX.Element> = {
  pronunciation: Icon.mic,
  fluency: Icon.wave,
  confidence: Icon.shield,
  grammar: Icon.pen,
  vocabulary: Icon.words,
  listening: Icon.ear,
  coherence: Icon.chat,
  relevance: Icon.spark,
};
