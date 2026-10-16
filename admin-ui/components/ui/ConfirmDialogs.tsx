"use client";

import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { dangerBtn, ghostBtn, inputCls } from "./classes";

const NAME_SLOT = "\u0000";

/** Pass as the `name` variable of a translation, then hand the result to `withName`. */
export const nameSlot = NAME_SLOT;

/** Swaps the name slot of a translated sentence for a highlighted chip. */
export function withName(text: string, name: string) {
  const [before, ...rest] = text.split(NAME_SLOT);
  return (
    <>
      {before}
      {rest.map((after, i) => (
        <span key={i}>
          <strong className="mx-0.5 inline-block max-w-full break-all rounded-md bg-destructive/12 px-1.5 py-0.5 align-baseline font-mono text-[13px] font-semibold text-destructive">
            {name}
          </strong>
          {after}
        </span>
      ))}
    </>
  );
}

type T = (key: string, vars?: Record<string, string | number>) => string;

/** Delete confirmation: the name must be typed, never pasted. `ns` points at a `delete` block of strings. */
export function DeleteDialog({
  name,
  busy,
  ns,
  t,
  onConfirm,
  onClose,
}: {
  name: string;
  busy: boolean;
  ns: string;
  t: T;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [input, setInput] = useState("");
  return (
    <Dialog title={t(`${ns}.title`)} closeLabel={t(`${ns}.cancel`)} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (input === name) onConfirm();
        }}
      >
        <p className="text-sm text-muted-foreground">{withName(t(`${ns}.body`, { name: NAME_SLOT }), name)}</p>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm">{withName(t(`${ns}.confirm_label`, { name: NAME_SLOT }), name)}</span>
          <input
            autoFocus
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={(e) => e.preventDefault()}
            onDrop={(e) => e.preventDefault()}
            onBeforeInput={(e) => {
              const kind = (e.nativeEvent as InputEvent).inputType;
              if (kind === "insertFromPaste" || kind === "insertFromDrop" || kind === "insertFromYank") e.preventDefault();
            }}
            className={cn(inputCls, "font-mono")}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} onClick={onClose}>
            {t(`${ns}.cancel`)}
          </button>
          <button type="submit" disabled={input !== name || busy} className={dangerBtn}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Trash2 className="h-3.5 w-3.5" aria-hidden />}
            {busy ? t(`${ns}.deleting`) : t(`${ns}.confirm`)}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Asks before unsaved edits are thrown away. `ns` points at a `leave` block of strings. */
export function LeaveDialog({ ns, t, onStay, onLeave }: { ns: string; t: T; onStay: () => void; onLeave: () => void }) {
  return (
    <Dialog title={t(`${ns}.title`)} closeLabel={t(`${ns}.stay`)} onClose={onStay}>
      <div className="flex flex-col gap-5">
        <p className="text-sm text-muted-foreground">{t(`${ns}.body`)}</p>
        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} autoFocus onClick={onStay}>
            {t(`${ns}.stay`)}
          </button>
          <button type="button" className={dangerBtn} onClick={onLeave}>
            {t(`${ns}.discard`)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
