"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice } from "@/components/ui/feedback";
import { FieldHint, Input, Label } from "@/components/ui/input";
import { useChangePassword } from "@/lib/queries";

// Mirrors the API's rule (core/security.py); the API remains the authority.
const MIN_LENGTH = 10;

function PasswordForm({ onDone }: { onDone: () => void }) {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const mismatch = confirm.length > 0 && next !== confirm;

  async function submit(event: FormEvent) {
    event.preventDefault();
    await change.mutateAsync({ current_password: current, new_password: next });
    toast.success("Password changed. Your other sessions were signed out.");
    onDone();
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="current-password">Current password</Label>
        <Input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="new-password">New password</Label>
        <Input
          id="new-password"
          type="password"
          autoComplete="new-password"
          value={next}
          minLength={MIN_LENGTH}
          onChange={(e) => setNext(e.target.value)}
          required
        />
        <FieldHint>At least {MIN_LENGTH} characters.</FieldHint>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="confirm-password">Confirm the new password</Label>
        <Input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={mismatch || undefined}
          required
        />
        {mismatch ? (
          <FieldHint className="text-danger">The passwords do not match.</FieldHint>
        ) : null}
      </div>
      {change.error ? <ErrorNotice message={change.error.message} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={!current || next.length < MIN_LENGTH || next !== confirm || change.isPending}
        >
          Change password
        </Button>
      </DialogFooter>
    </form>
  );
}

export function PasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Change your password"
        description="Every other browser and device signed in as you is signed out."
      >
        <PasswordForm onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
