import { CircleAlertIcon } from "lucide-react";
import { useId, useState } from "react";
import type { FormEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Spinner } from "~/components/ui/spinner";

import type { AdminSession } from "./useAdminSession";

/** Asks for the admin token. The token goes to memory only, never to browser storage. */
export function TokenForm({ session }: { session: AdminSession }) {
  const [token, setToken] = useState("");
  const id = useId();
  const error = session.error;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void session.signIn(token);
  };

  return (
    <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-4 py-10">
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4" aria-labelledby={`${id}-title`}>
        <div className="flex flex-col gap-1.5">
          <h2 id={`${id}-title`} className="m-0 text-xl font-medium tracking-tight text-foreground">
            Admin sign-in
          </h2>
          <p className="m-0 text-sm leading-relaxed text-muted-foreground">
            Enter the admin token to manage documents and see inquiries.
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-token`}>Admin token</Label>
          <Input
            id={`${id}-token`}
            name="admin-token"
            type="password"
            autoComplete="off"
            value={token}
            disabled={session.checking}
            aria-invalid={error ? true : undefined}
            aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}
            onChange={(event) => setToken(event.target.value)}
          />
          <p id={`${id}-hint`} className="m-0 text-xs leading-relaxed text-muted-foreground">
            The token stays in memory for this page only. Reloading the page signs you out.
          </p>
        </div>
        {error ? (
          <Alert variant="error" controlAlignment="first-line" id={`${id}-error`}>
            <CircleAlertIcon aria-hidden />
            <AlertTitle>{error.title}</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : null}
        <div>
          <Button type="submit" disabled={session.checking}>
            {session.checking ? <Spinner aria-hidden /> : null}
            {session.checking ? "Checking" : "Sign in"}
          </Button>
        </div>
      </form>
    </div>
  );
}
