"use client";

import { useState, useEffect, useRef } from "react";
import { ChevronDown, Search, X } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DropdownItem {
  /** Unique key used for selection comparison */
  key: string;
  /** Label displayed in the list */
  label: string;
}

export interface DropdownAction {
  /** Lucide icon (or any ReactNode) shown to the left of the label */
  icon: React.ReactNode;
  /** Action button label */
  label: string;
  /** Called when the user clicks this action */
  onClick: () => void;
  /**
   * Tailwind classes for text + hover background colour.
   * Defaults to blue if omitted.
   * Example: "text-emerald-400 hover:bg-emerald-600/10"
   */
  colorClass?: string;
}

export interface HeaderDropdownProps {
  // ── Trigger button content ─────────────────────────────────────────────
  /** Icon shown on the left side of the trigger button */
  triggerIcon: React.ReactNode;
  /** Small uppercase label above the main text (e.g. "Active Identity") */
  triggerLabelTop: string;
  /** Main label text — typically the selected item name or a placeholder */
  triggerLabelMain: string;

  // ── Items list ─────────────────────────────────────────────────────────
  items: DropdownItem[];
  /** Key of the currently selected item — used to highlight the active row */
  selectedKey?: string;
  /** Icon shown next to each item in the list */
  itemIcon: React.ReactNode;
  /** Called with the item key when the user selects an item */
  onItemSelect: (key: string) => void;

  // ── Search ─────────────────────────────────────────────────────────────
  /** Placeholder for the search input (default: "Search...") */
  searchPlaceholder?: string;
  /** Label shown when no items match the search (default: "No results found") */
  emptyLabel?: string;

  // ── Footer actions ─────────────────────────────────────────────────────
  /**
   * Ordered list of action buttons rendered at the bottom of the dropdown,
   * each separated by a top border.
   */
  actions: DropdownAction[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HeaderDropdown({
  triggerIcon,
  triggerLabelTop,
  triggerLabelMain,
  items,
  selectedKey,
  itemIcon,
  onItemSelect,
  searchPlaceholder = "Search...",
  emptyLabel = "No results found",
  actions,
}: HeaderDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  // Reset search query whenever the dropdown closes
  useEffect(() => {
    if (!isOpen) setSearch("");
  }, [isOpen]);

  // Close when clicking outside the component
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const filteredItems = items.filter((item) =>
    item.label.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelect = (key: string) => {
    onItemSelect(key);
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={containerRef}>
      {/* ── Trigger button ─────────────────────────────────────────────── */}
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-3 px-4 py-2 bg-[#121212] border border-slate-800 hover:border-slate-600 rounded-xl transition-all text-left min-w-0 max-w-xs sm:max-w-sm"
      >
        <div className="p-1.5 bg-blue-500/10 text-blue-500 rounded-md shrink-0">
          {triggerIcon}
        </div>
        <div className="text-left pr-4 min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold truncate">
            {triggerLabelTop}
          </div>
          <div className="text-base font-bold text-white truncate">
            {triggerLabelMain}
          </div>
        </div>
        <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
      </button>

      {/* ── Dropdown panel ─────────────────────────────────────────────── */}
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-64 bg-[#121212] border border-slate-800 rounded-xl shadow-2xl overflow-hidden z-50">

          {/* Search input */}
          <div className="p-2.5 border-b border-slate-800">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
              <input
                type="text"
                placeholder={searchPlaceholder}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-[#0a0a0a] border border-slate-800 rounded-lg pl-8 pr-7 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 outline-none transition-all"
                // Prevent the parent button's click-outside-close from firing
                onClick={(e) => e.stopPropagation()}
              />
              {search && (
                <button
                  onClick={() => setSearch("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-200"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Scrollable items list */}
          <div className="max-h-60 overflow-y-auto custom-scrollbar">
            {filteredItems.map((item) => (
              <button
                key={item.key}
                onClick={() => handleSelect(item.key)}
                className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/50 transition-colors text-left min-w-0 ${
                  selectedKey === item.key
                    ? "bg-slate-800/30 text-white"
                    : "text-slate-400"
                }`}
              >
                <span className="shrink-0 text-slate-400">{itemIcon}</span>
                <span className="text-sm font-medium truncate min-w-0">
                  {item.label}
                </span>
              </button>
            ))}
            {filteredItems.length === 0 && (
              <div className="text-center text-xs text-slate-600 py-4 italic">
                {emptyLabel}
              </div>
            )}
          </div>

          {/* Footer actions */}
          {actions.map((action, idx) => (
            <div key={idx} className="border-t border-slate-800">
              <button
                onClick={() => {
                  action.onClick();
                  setIsOpen(false);
                }}
                className={`w-full flex items-center gap-3 px-4 py-3 transition-colors text-left font-semibold text-sm ${
                  action.colorClass ?? "text-blue-400 hover:bg-blue-600/10"
                }`}
              >
                {action.icon}
                <span>{action.label}</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
