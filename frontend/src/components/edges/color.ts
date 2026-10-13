export interface HsvColor {
  hue: number;
  saturation: number;
  value: number;
}

const HEX_COLOR = /^#?([0-9a-f]{6})$/i;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function normalizeHexColor(value: string): string | null {
  const match = HEX_COLOR.exec(value.trim());
  return match?.[1] ? `#${match[1].toUpperCase()}` : null;
}

export function hexToHsv(value: string): HsvColor {
  const normalized = normalizeHexColor(value);
  if (!normalized) return { hue: 0, saturation: 0, value: 0 };

  const red = Number.parseInt(normalized.slice(1, 3), 16) / 255;
  const green = Number.parseInt(normalized.slice(3, 5), 16) / 255;
  const blue = Number.parseInt(normalized.slice(5, 7), 16) / 255;
  const maximum = Math.max(red, green, blue);
  const minimum = Math.min(red, green, blue);
  const delta = maximum - minimum;
  let hue = 0;

  if (delta !== 0) {
    if (maximum === red) hue = 60 * (((green - blue) / delta) % 6);
    else if (maximum === green) hue = 60 * ((blue - red) / delta + 2);
    else hue = 60 * ((red - green) / delta + 4);
  }

  const normalizedHue = hue < 0 ? hue + 360 : hue;
  return {
    hue: Math.round(normalizedHue) % 360,
    saturation: maximum === 0 ? 0 : Math.round((delta / maximum) * 100),
    value: Math.round(maximum * 100),
  };
}

export function hsvToHex({
  hue,
  saturation,
  value,
}: HsvColor): string {
  const normalizedHue = ((Math.round(hue) % 360) + 360) % 360;
  const normalizedSaturation = clamp(saturation, 0, 100) / 100;
  const normalizedValue = clamp(value, 0, 100) / 100;
  const chroma = normalizedValue * normalizedSaturation;
  const section = normalizedHue / 60;
  const secondary = chroma * (1 - Math.abs((section % 2) - 1));
  const match = normalizedValue - chroma;

  let red = 0;
  let green = 0;
  let blue = 0;
  if (section < 1) [red, green] = [chroma, secondary];
  else if (section < 2) [red, green] = [secondary, chroma];
  else if (section < 3) [green, blue] = [chroma, secondary];
  else if (section < 4) [green, blue] = [secondary, chroma];
  else if (section < 5) [red, blue] = [secondary, chroma];
  else [red, blue] = [chroma, secondary];

  return `#${[red, green, blue]
    .map((channel) =>
      Math.round((channel + match) * 255)
        .toString(16)
        .padStart(2, "0")
        .toUpperCase(),
    )
    .join("")}`;
}
