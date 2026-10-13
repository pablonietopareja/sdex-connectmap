import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ChevronDownIcon } from "./icons";

export interface SelectMenuOption<T extends string | number> {
  value: T;
  label: string;
}

interface SelectMenuProps<T extends string | number> {
  ariaLabel: string;
  value: T;
  options: readonly SelectMenuOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  leading?: ReactNode;
}

export function SelectMenu<T extends string | number>({
  ariaLabel,
  value,
  options,
  onChange,
  className = "",
  leading,
}: SelectMenuProps<T>) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(selectedIndex);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) setActiveIndex(selectedIndex);
  }, [open, selectedIndex]);

  const select = (index: number) => {
    const option = options[index];
    if (!option) return;
    onChange(option.value);
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const move = (delta: number) => {
    setActiveIndex((current) => {
      const length = options.length;
      return length ? (current + delta + length) % length : 0;
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (!open) setOpen(true);
        else move(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (!open) setOpen(true);
        else move(-1);
        break;
      case "Home":
        if (open) {
          event.preventDefault();
          setActiveIndex(0);
        }
        break;
      case "End":
        if (open) {
          event.preventDefault();
          setActiveIndex(Math.max(0, options.length - 1));
        }
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        if (open) select(activeIndex);
        else setOpen(true);
        break;
      case "Escape":
        if (open) {
          event.preventDefault();
          setOpen(false);
        }
        break;
      case "Tab":
        setOpen(false);
        break;
      default:
        break;
    }
  };

  const selected = options[selectedIndex];

  return (
    <div
      ref={rootRef}
      className={`select-menu ${className}${open ? " is-open" : ""}`}
    >
      <button
        ref={triggerRef}
        type="button"
        className="select-menu-trigger"
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-listbox`}
        aria-activedescendant={open ? `${id}-option-${activeIndex}` : undefined}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onKeyDown}
      >
        {leading && <span className="select-menu-leading">{leading}</span>}
        <span className="select-menu-value">{selected?.label}</span>
        <ChevronDownIcon />
      </button>
      {open && (
        <ul
          id={`${id}-listbox`}
          className="select-menu-popup"
          role="listbox"
          aria-label={ariaLabel}
        >
          {options.map((option, index) => (
            <li
              id={`${id}-option-${index}`}
              key={String(option.value)}
              role="option"
              aria-selected={option.value === value}
              className={[
                "select-menu-option",
                index === activeIndex ? "is-active" : "",
                option.value === value ? "is-selected" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onPointerMove={() => setActiveIndex(index)}
              onPointerDown={(event) => {
                event.preventDefault();
                select(index);
              }}
            >
              {option.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
