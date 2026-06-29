"use client";

import React, { useEffect, useState } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";

export function CustomDatePicker({ label, value, onChange, minDate, maxDate, placeholder = "Seleziona data" }: { label: string; value: string; onChange: (val: string) => void; minDate?: string; maxDate?: string; placeholder?: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const [currentDate] = useState(() => {
    if (value) {
      const parts = value.split("-");
      if (parts.length === 3) {
        return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
      }
    }
    return new Date();
  });

  const [viewMonth, setViewMonth] = useState(currentDate.getMonth());
  const [viewYear, setViewYear] = useState(currentDate.getFullYear());

  useEffect(() => {
    if (value) {
      const parts = value.split("-");
      if (parts.length === 3) {
        const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        setViewMonth(d.getMonth());
        setViewYear(d.getFullYear());
      }
    }
  }, [value]);

  const monthNames = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
  ];
  const weekDays = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

  const firstDayIndex = new Date(viewYear, viewMonth, 1).getDay();
  const startOffset = firstDayIndex === 0 ? 6 : firstDayIndex - 1;
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const handlePrevMonth = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear(viewYear - 1);
    } else {
      setViewMonth(viewMonth - 1);
    }
  };

  const handleNextMonth = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear(viewYear + 1);
    } else {
      setViewMonth(viewMonth + 1);
    }
  };

  const handleSelectDay = (day: number) => {
    const formattedMonth = String(viewMonth + 1).padStart(2, "0");
    const formattedDay = String(day).padStart(2, "0");
    onChange(`${viewYear}-${formattedMonth}-${formattedDay}`);
    setIsOpen(false);
  };

  const formattedDisplay = value ? value.split("-").reverse().join("/") : "";

  return (
    <div className="relative">
      <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 block mb-1">{label}</label>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full bg-black/40 border border-white/10 hover:border-blue-500/50 rounded-xl px-3.5 py-2.5 text-xs text-white flex items-center justify-between transition-all shadow-inner cursor-pointer"
      >
        <span className={value ? "text-white font-semibold" : "text-gray-500"}>
          {formattedDisplay || placeholder}
        </span>
        <Calendar className="w-4 h-4 text-blue-400" />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute left-0 top-full mt-2 z-50 w-64 bg-[#1a1a1a] border border-white/15 rounded-2xl p-4 shadow-2xl backdrop-blur-xl animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between mb-3 pb-2 border-b border-white/10">
              <button
                type="button"
                onClick={handlePrevMonth}
                className="p-1 hover:bg-white/10 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <div className="text-xs font-bold text-white">
                {monthNames[viewMonth]} {viewYear}
              </div>
              <button
                type="button"
                onClick={handleNextMonth}
                className="p-1 hover:bg-white/10 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-7 gap-1 mb-2 text-center">
              {weekDays.map(wd => (
                <div key={wd} className="text-[10px] font-bold text-gray-500 py-1">
                  {wd}
                </div>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-1 text-center">
              {Array.from({ length: startOffset }).map((_, i) => (
                <div key={`empty-${i}`} className="py-1" />
              ))}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const day = i + 1;
                const formattedMonth = String(viewMonth + 1).padStart(2, "0");
                const formattedDay = String(day).padStart(2, "0");
                const dateStr = `${viewYear}-${formattedMonth}-${formattedDay}`;
                const isSelected = value === dateStr;
                const isDisabled = (minDate ? dateStr < minDate : false) || (maxDate ? dateStr > maxDate : false);

                return (
                  <button
                    key={day}
                    type="button"
                    disabled={isDisabled}
                    onClick={() => handleSelectDay(day)}
                    className={`py-1.5 text-xs rounded-lg font-medium transition-all ${
                      isDisabled
                        ? "opacity-25 cursor-not-allowed text-gray-500"
                        : isSelected
                        ? "bg-blue-600 text-white shadow-lg shadow-blue-600/30 font-bold cursor-pointer"
                        : "text-gray-300 hover:bg-white/10 hover:text-white cursor-pointer"
                    }`}
                  >
                    {day}
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
