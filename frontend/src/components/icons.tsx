import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const icon = (children: React.ReactNode, props: IconProps) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    {...props}
  >
    {children}
  </svg>
);

export const RefreshIcon = (props: IconProps) =>
  icon(
    <>
      <path d="M20 7v5h-5" />
      <path d="M4.7 9A8 8 0 0 1 18.8 6.2L20 8" />
      <path d="M4 17v-5h5" />
      <path d="M19.3 15A8 8 0 0 1 5.2 17.8L4 16" />
    </>,
    props,
  );

export const SettingsIcon = (props: IconProps) =>
  icon(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </>,
    props,
  );

export const SunIcon = (props: IconProps) =>
  icon(
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>,
    props,
  );

export const MoonIcon = (props: IconProps) =>
  icon(<path d="M20.8 15.1A8.5 8.5 0 0 1 8.9 3.2 8.5 8.5 0 1 0 20.8 15.1Z" />, props);

export const MonitorIcon = (props: IconProps) =>
  icon(
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>,
    props,
  );

export const CloseIcon = (props: IconProps) =>
  icon(<path d="m6 6 12 12M18 6 6 18" />, props);

export const ChevronDownIcon = (props: IconProps) =>
  icon(<path d="m7 9 5 5 5-5" />, props);

export const ZoomInIcon = (props: IconProps) =>
  icon(
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5M10.5 7.5v6M7.5 10.5h6" />
    </>,
    props,
  );

export const ZoomOutIcon = (props: IconProps) =>
  icon(
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5M7.5 10.5h6" />
    </>,
    props,
  );

export const FitIcon = (props: IconProps) =>
  icon(
    <>
      <path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5" />
      <path d="m3 8 5-5M16 3l5 5M21 16l-5 5M8 21l-5-5" />
    </>,
    props,
  );

export const FocusIcon = (props: IconProps) =>
  icon(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </>,
    props,
  );

export const LayoutIcon = (props: IconProps) =>
  icon(
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>,
    props,
  );

export const InfoIcon = (props: IconProps) =>
  icon(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>,
    props,
  );

export const AlertIcon = (props: IconProps) =>
  icon(
    <>
      <path d="M10.3 3.8 2.1 18a2 2 0 0 0 1.7 3h16.4a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4M12 17h.01" />
    </>,
    props,
  );

export const CheckIcon = (props: IconProps) =>
  icon(<path d="m5 12 4 4L19 6" />, props);

export const LockIcon = (props: IconProps) =>
  icon(
    <>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>,
    props,
  );

export const EditIcon = (props: IconProps) =>
  icon(
    <>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" />
    </>,
    props,
  );

export const EyeIcon = (props: IconProps) =>
  icon(
    <>
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
      <circle cx="12" cy="12" r="2.5" />
    </>,
    props,
  );

export const NetworkIcon = (props: IconProps) =>
  icon(
    <>
      <rect x="8" y="3" width="8" height="5" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
      <rect x="14" y="16" width="7" height="5" rx="1" />
      <path d="M12 8v4M6.5 16v-4h11v4" />
    </>,
    props,
  );

export const ArrowRightIcon = (props: IconProps) =>
  icon(<path d="M5 12h14M13 6l6 6-6 6" />, props);
