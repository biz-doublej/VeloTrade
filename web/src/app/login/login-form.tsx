"use client";

import { useState, useTransition } from "react";
import { sendMagicLink } from "./actions";

export function LoginForm() {
  const [pending, start] = useTransition();
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (sentTo) {
    return (
      <div className="rounded-lg border border-border bg-card/30 p-8 max-w-sm w-full text-center">
        <div className="text-4xl mb-3">✉️</div>
        <h2 className="text-lg font-semibold mb-2">Check your email</h2>
        <p className="text-sm text-muted-foreground">
          Magic link sent to <span className="font-mono">{sentTo}</span>.
          <br />
          Click the link in the email to sign in.
        </p>
        <button
          onClick={() => {
            setSentTo(null);
            setError(null);
          }}
          className="mt-4 text-xs underline text-muted-foreground hover:text-foreground"
        >
          Use a different email
        </button>
      </div>
    );
  }

  return (
    <form
      action={(fd) =>
        start(async () => {
          setError(null);
          const email = String(fd.get("email") || "").trim();
          const r = await sendMagicLink(fd);
          if (r?.error) setError(r.error);
          else if (r?.sent) setSentTo(email);
        })
      }
      className="rounded-lg border border-border bg-card/30 p-8 max-w-sm w-full"
    >
      <h1 className="text-2xl font-bold tracking-tight mb-1">Sign in</h1>
      <p className="text-sm text-muted-foreground mb-6">
        VeloTrade dashboard — magic link via email
      </p>

      <label className="block text-xs text-muted-foreground mb-1">Email</label>
      <input
        type="email"
        name="email"
        required
        autoFocus
        placeholder="you@example.com"
        className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm mb-3"
      />

      <button
        disabled={pending}
        className="w-full px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
      >
        {pending ? "Sending…" : "Send magic link"}
      </button>

      {error ? (
        <p className="mt-3 text-xs text-rose-400 text-center">{error}</p>
      ) : null}
    </form>
  );
}
