import { useEffect, useRef, useState } from "react";
import type { ComponentPropsWithoutRef } from "react";

type Props = Omit<ComponentPropsWithoutRef<"input">, "value" | "defaultValue" | "onChange" | "onCompositionStart" | "onCompositionEnd"> & {
  value: string;
  onValueChange: (value: string) => void;
};

export function ImeSearchInput({value, onValueChange, ...props}: Props) {
  const [draft, setDraft] = useState(value);
  const composing = useRef(false);
  const published = useRef(value);
  const pending = useRef(new Set<string>());

  useEffect(() => {
    // Router updates can arrive after a newer keystroke. Acknowledging our
    // own update must not overwrite the draft or move the IME caret.
    if (pending.current.has(value)) {
      if (value === published.current) pending.current.clear();
      else pending.current.delete(value);
      return;
    }
    if (!composing.current) {
      pending.current.clear();
      published.current = value;
      setDraft(value);
    }
  }, [value]);

  function publish(next: string) {
    if (next === published.current) return;
    published.current = next;
    pending.current.add(next);
    onValueChange(next);
  }

  return <input {...props} value={draft}
    onCompositionStart={() => { composing.current = true; }}
    onCompositionEnd={event => {
      composing.current = false;
      const next = event.currentTarget.value;
      setDraft(next);
      publish(next);
    }}
    onChange={event => {
      const next = event.currentTarget.value;
      setDraft(next);
      if (!composing.current && !(event.nativeEvent as InputEvent).isComposing) publish(next);
    }} />;
}
