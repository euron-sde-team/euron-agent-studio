"use client";

import { Braces, Plus, Search, Trash2 } from "lucide-react";
import {
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { Button } from "@/components/ui/button";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import type { Issue } from "@/lib/types";
import { partialReference, type Variable } from "@/lib/variables";

export const mono = "font-mono text-[12.5px]";

/** The first issue reported for a field path, or for something inside it. */
export function issueAt(issues: Issue[], path: string): string | undefined {
  return issues.find(
    (issue) =>
      issue.field === path ||
      (issue.field?.startsWith(`${path}.`) ?? false) ||
      (path === "" && !issue.field),
  )?.message;
}

export function FieldShell({
  id,
  label,
  hint,
  error,
  template,
  action,
  children,
  inline,
}: {
  id?: string;
  label: string;
  hint?: ReactNode;
  error?: string;
  template?: boolean;
  action?: ReactNode;
  children: ReactNode;
  inline?: boolean;
}) {
  return (
    <div
      className={cn("space-y-1.5", inline && "flex items-center justify-between gap-3 space-y-0")}
    >
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        {template ? (
          <span
            className="bg-accent text-accent-foreground inline-flex items-center gap-0.5 rounded px-1 text-[10.5px] font-medium"
            title="Accepts {{ references }} to inputs and earlier steps"
          >
            <Braces className="size-3" aria-hidden />
            template
          </span>
        ) : null}
        {action ? <span className="ml-auto">{action}</span> : null}
      </div>
      {children}
      {hint && !inline ? <FieldHint>{hint}</FieldHint> : null}
      {error ? (
        <p className="text-danger text-xs font-medium" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function VariableList({
  variables,
  query,
  active,
  onPick,
}: {
  variables: Variable[];
  query: string;
  active?: number;
  onPick: (variable: Variable) => void;
}) {
  const filtered = variables.filter((v) => v.path.toLowerCase().includes(query.toLowerCase()));
  if (!filtered.length) {
    return <p className="text-muted-foreground px-2 py-1.5 text-xs">Nothing matches.</p>;
  }
  const groups = [...new Set(filtered.map((v) => v.group))];
  return (
    <div className="max-h-64 overflow-y-auto">
      {groups.map((group) => (
        <div key={group} className="pb-1">
          <p className="text-subtle px-2 pt-1.5 pb-0.5 text-[10.5px] font-medium tracking-wider uppercase">
            {group}
          </p>
          {filtered
            .filter((v) => v.group === group)
            .map((variable) => {
              const index = filtered.indexOf(variable);
              return (
                <button
                  key={variable.path}
                  type="button"
                  // Keep focus in the field: pick on mouse down, before the blur.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onPick(variable);
                  }}
                  className={cn(
                    "hover:bg-muted flex w-full flex-col rounded-md px-2 py-1 text-left",
                    active === index && "bg-muted",
                  )}
                >
                  <code className="text-foreground font-mono text-[12px]">{variable.path}</code>
                  <span className="text-muted-foreground truncate text-[11px]">
                    {variable.description}
                  </span>
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}

/**
 * A text field for the template language: `{{` opens suggestions of everything this node can
 * read (inputs, earlier steps, loop items, tool arguments, secrets), and the braces button
 * lists them all.
 */
export function TemplateField({
  label,
  value,
  onChange,
  variables,
  multiline = false,
  rows = 4,
  placeholder,
  hint,
  error,
  disabled,
  monospace = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  variables: Variable[];
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
  hint?: ReactNode;
  error?: string;
  disabled?: boolean;
  monospace?: boolean;
}) {
  const id = useId();
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const [suggest, setSuggest] = useState<{ start: number; query: string } | null>(null);
  const [active, setActive] = useState(0);
  const [search, setSearch] = useState("");
  const matches = useMemo(
    () =>
      suggest
        ? variables.filter((v) => v.path.toLowerCase().includes(suggest.query.toLowerCase()))
        : [],
    [suggest, variables],
  );

  function refresh(text: string, caret: number | null) {
    const found = caret === null ? null : partialReference(text, caret);
    setSuggest(found);
    setActive(0);
  }

  function insert(variable: Variable, replaceFrom?: number) {
    const element = ref.current;
    const caret = element?.selectionStart ?? value.length;
    const start = replaceFrom ?? caret;
    const after = value.slice(caret);
    const closing = after.startsWith("}}") ? "" : "}}";
    const text = `${value.slice(0, start)}{{${variable.path}${closing}${after}`;
    onChange(text);
    setSuggest(null);
    const position = start + variable.path.length + 4;
    requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(position, position);
    });
  }

  function onKeyDown(event: KeyboardEvent) {
    if (!suggest || !matches.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((a) => Math.min(a + 1, matches.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      insert(matches[active]!, suggest.start);
    } else if (event.key === "Escape") {
      event.stopPropagation();
      setSuggest(null);
    }
  }

  const shared = {
    id,
    value,
    disabled,
    placeholder,
    spellCheck: false,
    className: cn(monospace && mono, error && "border-danger"),
    onKeyDown,
    onBlur: () => setSuggest(null),
    onClick: (event: { currentTarget: HTMLInputElement | HTMLTextAreaElement }) =>
      refresh(event.currentTarget.value, event.currentTarget.selectionStart),
    onChange: (event: { target: HTMLInputElement | HTMLTextAreaElement }) => {
      onChange(event.target.value);
      refresh(event.target.value, event.target.selectionStart);
    },
  };

  const picker = (
    <Popover onOpenChange={() => setSearch("")}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-[11.5px]"
          disabled={disabled || !variables.length}
          aria-label={`Insert a reference into ${label}`}
        >
          <Braces /> Insert
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-2">
        <div className="relative mb-1.5">
          <Search
            className="text-subtle pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search references"
            className="h-8 pl-8 text-[13px]"
            aria-label="Search references"
          />
        </div>
        <VariableList variables={variables} query={search} onPick={(v) => insert(v)} />
      </PopoverContent>
    </Popover>
  );

  return (
    <FieldShell id={id} label={label} hint={hint} error={error} template action={picker}>
      <div className="relative">
        {multiline ? (
          <Textarea ref={ref as RefObject<HTMLTextAreaElement>} rows={rows} {...shared} />
        ) : (
          <Input ref={ref as RefObject<HTMLInputElement>} {...shared} />
        )}
        {suggest && matches.length ? (
          <div
            className="border-border bg-card absolute inset-x-0 top-full z-30 mt-1 rounded-lg border p-1 shadow-md"
            role="listbox"
            aria-label="References"
          >
            <VariableList
              variables={matches}
              query=""
              active={active}
              onPick={(v) => insert(v, suggest.start)}
            />
          </div>
        ) : null}
      </div>
    </FieldShell>
  );
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  disabled,
  monospace,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: ReactNode;
  error?: string;
  disabled?: boolean;
  monospace?: boolean;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        className={cn(monospace && mono, error && "border-danger")}
        onChange={(e) => onChange(e.target.value)}
      />
    </FieldShell>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  hint,
  error,
  disabled,
  nullable,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number | "any";
  hint?: ReactNode;
  error?: string;
  disabled?: boolean;
  nullable?: boolean;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <Input
        id={id}
        type="number"
        className="tabular-nums"
        value={value === null || value === undefined ? "" : String(value)}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        placeholder={nullable ? "None" : undefined}
        onChange={(e) =>
          onChange(e.target.value === "" ? (nullable ? null : (min ?? 0)) : Number(e.target.value))
        }
      />
    </FieldShell>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  hint,
  error,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  hint?: ReactNode;
  error?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <NativeSelect
        id={id}
        value={value}
        disabled={disabled}
        className={cn(error && "border-danger")}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </NativeSelect>
    </FieldShell>
  );
}

export function SwitchField({
  label,
  checked,
  onChange,
  hint,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor={id}>{label}</Label>
        <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
      </div>
      {hint ? <FieldHint>{hint}</FieldHint> : null}
    </div>
  );
}

type Row = Record<string, unknown>;

/** A list of small records (headers, fields, rules) edited in place. */
export function RowList<T extends Row>({
  rows,
  onChange,
  make,
  render,
  addLabel,
  empty,
  disabled,
  max,
}: {
  rows: T[];
  onChange: (rows: T[]) => void;
  make: () => T;
  render: (row: T, update: (patch: Partial<T>) => void, index: number) => ReactNode;
  addLabel: string;
  empty?: string;
  disabled?: boolean;
  max?: number;
}) {
  return (
    <div className="space-y-2">
      {rows.length === 0 && empty ? <p className="text-subtle text-xs">{empty}</p> : null}
      {rows.map((row, index) => (
        <div key={index} className="flex items-start gap-1.5">
          <div className="min-w-0 flex-1">
            {render(
              row,
              (patch) => onChange(rows.map((r, i) => (i === index ? { ...r, ...patch } : r))),
              index,
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={disabled}
            aria-label="Remove"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled={disabled || (max !== undefined && rows.length >= max)}
        onClick={() => onChange([...rows, make()])}
      >
        <Plus /> {addLabel}
      </Button>
    </div>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-border space-y-4 border-t pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-subtle text-[11px] font-medium tracking-wider uppercase">{title}</h3>
      {children}
    </section>
  );
}
