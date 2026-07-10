// The single stroke-icon family (1.6px line weight, brass-on-dark) that replaces
// every emoji in the UI. Purely presentational; colour comes from currentColor.

interface IconProps {
  size?: number;
  className?: string;
  strokeWidth?: number;
}

function make(paths: React.ReactNode, defaultStroke = 1.6) {
  return function Icon({ size = 16, className = "", strokeWidth = defaultStroke }: IconProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-hidden
      >
        {paths}
      </svg>
    );
  };
}

export const IconSword = make(
  <>
    <path d="M19 4 8.5 14.5" />
    <path d="M19 4l-3.6.3M19 4l-.3 3.6" />
    <path d="M6.3 12.3l5.4 5.4" />
    <path d="M8.6 15.9 4.5 20" />
  </>,
);

export const IconShield = make(
  <path d="M12 3.5l6.5 2.6v5.2c0 4.6-3.1 7.4-6.5 9.2-3.4-1.8-6.5-4.6-6.5-9.2V6.1z" />,
);

export const IconMend = make(
  <>
    <path d="M12 4.5l7.5 7.5-7.5 7.5L4.5 12z" />
    <path d="M12 9.5v5M9.5 12h5" />
  </>,
);

export const IconMove = make(
  <>
    <path d="M4.5 12h14" />
    <path d="M13.5 7l5 5-5 5" />
  </>,
);

export const IconLibrary = make(
  <>
    <rect x="7.5" y="3.5" width="11" height="15" rx="1" />
    <path d="M5 6.5v13a1.5 1.5 0 0 0 1.5 1.5H15" />
  </>,
);

export const IconGrave = make(
  <>
    <path d="M7 20v-9.5a5 5 0 0 1 10 0V20" />
    <path d="M5 20h14" />
    <path d="M12 9.5v4M10.2 11h3.6" />
  </>,
);

export const IconChannel = make(
  <>
    <path d="M9 4c2.2 2 2.2 4.5 0 6.5s-2.2 4.5 0 6.5" />
    <path d="M15 4c-2.2 2-2.2 4.5 0 6.5s2.2 4.5 0 6.5" />
  </>,
);

export const IconLink = make(
  <>
    <path d="M10 14a5 5 0 0 0 7.1 0l2.4-2.4a5 5 0 0 0-7.1-7.1L11 5.9" />
    <path d="M14 10a5 5 0 0 0-7.1 0l-2.4 2.4a5 5 0 0 0 7.1 7.1L13 18.1" />
  </>,
);

export const IconGear = make(
  <>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 2.8v2.6M12 18.6v2.6M2.8 12h2.6M18.6 12h2.6M5.5 5.5l1.8 1.8M16.7 16.7l1.8 1.8M18.5 5.5l-1.8 1.8M7.3 16.7l-1.8 1.8" />
  </>,
);

export const IconPlus = make(<path d="M12 5v14M5 12h14" />);

export const IconX = make(<path d="M6 6l12 12M18 6L6 18" />);

export const IconUpload = make(
  <>
    <path d="M12 16V4" />
    <path d="M7 9l5-5 5 5" />
    <path d="M5 20h14" />
  </>,
);

export const IconEdit = make(
  <>
    <path d="M4 20l.9-3.6L16.6 4.7a1.8 1.8 0 0 1 2.6 0l.1.1a1.8 1.8 0 0 1 0 2.6L7.6 19.1z" />
  </>,
);

// Art generation: an easel-framed landscape (generate) and a redraw cycle.
export const IconCanvas = make(
  <>
    <rect x="4" y="5" width="16" height="12" rx="0.5" />
    <circle cx="9" cy="9.2" r="1.4" />
    <path d="M4.5 15.5l4-4 3 3 3.5-3.5 4.5 4.5" />
    <path d="M8 21l1.5-4M16 21l-1.5-4" />
  </>,
);

export const IconRedraw = make(
  <>
    <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" />
    <path d="M19.8 3.5v3.6h-3.6" />
  </>,
);

export const IconSkull = make(
  <>
    <path d="M12 3.5c-4.7 0-8 3.3-8 7.6 0 2.6 1.3 4.6 3.2 5.9V20h2.3v-2h1.6v2h1.8v-2h1.6v2h2.3v-3c1.9-1.3 3.2-3.3 3.2-5.9 0-4.3-3.3-7.6-8-7.6z" />
    <circle cx="9" cy="11" r="1.7" />
    <circle cx="15" cy="11" r="1.7" />
  </>,
  1.1,
);

export const IconSigil = make(
  <>
    <path d="M12 3l9 9-9 9-9-9z" />
    <path d="M12 8l4 4-4 4-4-4z" />
  </>,
  1.1,
);

/* ---- keyword sigils (registry ids in core/ltg_core/schema.py) ---- */

const IconWing = make(
  <>
    <path d="M4.5 15.5C8 9 14 6 19.5 5.5c-1.5 6-6.5 10.5-13 11.5z" />
    <path d="M9 12c2.5-2.5 6-4 9-4.5" />
  </>,
);

const IconReach = make(
  <>
    <path d="M6 18 18 6" />
    <path d="M9.5 6H18v8.5" />
  </>,
);

const IconBolt = make(<path d="M13 3 6 13.5h5L10 21l7.5-10.5h-5z" />);

const IconDoubleSlash = make(<path d="M16.5 3 4.5 15M20.5 8 10 18.5" />);

const IconEye = make(
  <>
    <path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z" />
    <circle cx="12" cy="12" r="2.5" />
  </>,
);

const IconHaste = make(<path d="M5 5l7 7-7 7M12 5l7 7-7 7" />);

const IconTrample = make(<path d="M5 20 20 5M5 13.5 13.5 5M11.5 20 20 11.5" />);

const IconHeart = make(
  <path d="M12 20s-7-4.5-9-9c-1.2-2.8.6-6 3.8-6C9 5 11 6.6 12 8c1-1.4 3-3 5.2-3 3.2 0 5 3.2 3.8 6-2 4.5-9 9-9 9z" />,
);

const IconWard = make(
  <>
    <circle cx="12" cy="12" r="8" />
    <path d="M6.5 6.5l11 11" />
  </>,
);

const IconGem = make(
  <>
    <path d="M12 3l7 5-7 13L5 8z" />
    <path d="M5 8h14" />
  </>,
);

// One component per registry keyword; unknown keywords fall back to an initial.
export const KEYWORD_ICONS: Record<string, (p: IconProps) => JSX.Element> = {
  flying: IconWing,
  reach: IconReach,
  first_strike: IconBolt,
  double_strike: IconDoubleSlash,
  vigilance: IconEye,
  haste: IconHaste,
  trample: IconTrample,
  deathtouch: IconSkull,
  lifelink: IconHeart,
  hexproof: IconWard,
  indestructible: IconGem,
  protection: IconShield,
};
