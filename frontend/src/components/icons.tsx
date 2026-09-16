/**
 * Inline SVG icons. Hand-rolled rather than pulling an icon package — the app
 * needs a dozen glyphs, and a dependency would ship hundreds.
 *
 * All icons inherit `currentColor` and size from the `size` prop so they can
 * sit inline with text without alignment fiddling.
 */

interface IconProps {
  size?: number;
  className?: string;
}

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const IconDashboard = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </svg>
);

export const IconCampaign = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M3 11v2a1 1 0 0 0 1 1h2l4 4V6L6 10H4a1 1 0 0 0-1 1Z" />
    <path d="M15 9a3.5 3.5 0 0 1 0 6" />
    <path d="M18 6a7 7 0 0 1 0 12" />
  </svg>
);

export const IconPhone = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M5 3h3l2 5-2.5 1.5a12 12 0 0 0 6 6L15 13l5 2v3a2 2 0 0 1-2.2 2A17 17 0 0 1 3 5.2 2 2 0 0 1 5 3Z" />
  </svg>
);

export const IconReview = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3.5 3.5 18.5h17L12 3.5Z" />
    <path d="M12 10v3.5" />
    <path d="M12 16.5h.01" />
  </svg>
);

export const IconBlock = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M6 6l12 12" />
  </svg>
);

export const IconTrendUp = ({ size = 14, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M3 17l6-6 4 4 8-8" />
    <path d="M15 7h6v6" />
  </svg>
);

export const IconTrendDown = ({ size = 14, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M3 7l6 6 4-4 8 8" />
    <path d="M15 17h6v-6" />
  </svg>
);

export const IconCheck = ({ size = 14, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M4 12.5l5 5L20 6.5" />
  </svg>
);

export const IconClock = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7v5.5l3.5 2" />
  </svg>
);

export const IconUsers = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="9" cy="8" r="3.25" />
    <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
    <path d="M16 5.5a3.25 3.25 0 0 1 0 6.5" />
    <path d="M17.5 14.5a5.5 5.5 0 0 1 3 4.5" />
  </svg>
);

export const IconPlay = ({ size = 14, className }: IconProps) => (
  <svg {...base(size)} className={className} fill="currentColor" stroke="none">
    <path d="M8 5.5v13l11-6.5L8 5.5Z" />
  </svg>
);

export const IconPause = ({ size = 14, className }: IconProps) => (
  <svg {...base(size)} className={className} fill="currentColor" stroke="none">
    <rect x="7" y="5.5" width="3.5" height="13" rx="1" />
    <rect x="13.5" y="5.5" width="3.5" height="13" rx="1" />
  </svg>
);

export const IconUpload = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M12 16V4" />
    <path d="M7.5 8.5 12 4l4.5 4.5" />
    <path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" />
  </svg>
);

export const IconArrowLeft = ({ size = 14, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M19 12H5" />
    <path d="m11 6-6 6 6 6" />
  </svg>
);

export const IconCalendar = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
    <path d="M3.5 10h17" />
    <path d="M8 3v4M16 3v4" />
  </svg>
);

export const IconSparkle = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3.5 13.9 9l5.6 1.9-5.6 1.9L12 18.5l-1.9-5.7L4.5 11l5.6-1.9L12 3.5Z" />
    <path d="M18.5 4v3M20 5.5h-3" />
  </svg>
);

export const IconChip = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="7" y="7" width="10" height="10" rx="2" />
    <rect x="3.5" y="3.5" width="17" height="17" rx="3.5" />
    <path d="M9.5 3.5v-1.5M14.5 3.5v-1.5M9.5 22v-1.5M14.5 22v-1.5" />
    <path d="M3.5 9.5h-1.5M3.5 14.5h-1.5M22 9.5h-1.5M22 14.5h-1.5" />
  </svg>
);

export const IconFlask = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M10 3v6.5L4.6 18a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3L14 9.5V3" />
    <path d="M8.5 3h7" />
    <path d="M7.4 14h9.2" />
  </svg>
);

export const IconSearch = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="10.5" cy="10.5" r="6.5" />
    <path d="m15.5 15.5 4.5 4.5" />
  </svg>
);

export const IconDownload = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M12 4v12" />
    <path d="m7.5 11.5 4.5 4.5 4.5-4.5" />
    <path d="M4 20h16" />
  </svg>
);

export const IconCoin = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M14.5 9.2A2.8 2.8 0 0 0 12 8c-1.4 0-2.5.8-2.5 1.9s1.1 1.6 2.5 1.9 2.5.8 2.5 1.9S13.4 16 12 16a2.8 2.8 0 0 1-2.5-1.2" />
    <path d="M12 6.5v11" />
  </svg>
);

export const IconBolt = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M13 2.5 4.5 13.5H11l-.5 8L19 10.5h-6.5l.5-8Z" />
  </svg>
);

export const IconShield = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3l7 2.5v5.8c0 4.2-2.8 7.6-7 9.2-4.2-1.6-7-5-7-9.2V5.5L12 3Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

export const IconMic = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="9" y="2.5" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
    <path d="M12 17.5V21" />
  </svg>
);

export const IconMicOff = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M9 6a3 3 0 0 1 6 0v4m0 3.2a3 3 0 0 1-4.6-1.7" />
    <path d="M5.5 11a6.5 6.5 0 0 0 9.9 5.6M18.5 11v.4" />
    <path d="M12 17.5V21" />
    <path d="m4 3 16 18" />
  </svg>
);

export const IconClose = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="m6 6 12 12M18 6 6 18" />
  </svg>
);

export const IconInbox = ({ size = 32, className }: IconProps) => (
  <svg {...base(size)} className={className} strokeWidth={1.25}>
    <path d="M3.5 13.5h4l1.5 3h6l1.5-3h4" />
    <path d="M5.5 5h13l2 8.5v4a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-4L5.5 5Z" />
  </svg>
);

export const IconSun = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
  </svg>
);

export const IconMoon = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
  </svg>
);
