import { CircleAlertIcon } from "lucide-react";
import { useId, useState } from "react";
import type { FormEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "~/components/ui/alert";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogPopup,
  AlertDialogTitle,
} from "~/components/ui/alert-dialog";
import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogPanel,
  DialogPopup,
  DialogTitle,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Spinner } from "~/components/ui/spinner";

import type { DocumentRead } from "../../api/client";
import type { UiError } from "../../lib/errors";
import { ACCEPTED_EXTENSIONS, isAcceptedFile } from "./useDocuments";
import type { UploadInput } from "./useDocuments";

function ActionError({ error }: { error: UiError | null }) {
  if (error === null) return null;
  return (
    <Alert variant="error" controlAlignment="first-line">
      <CircleAlertIcon aria-hidden />
      <AlertTitle>{error.title}</AlertTitle>
      <AlertDescription>{error.message}</AlertDescription>
    </Alert>
  );
}

/**
 * Upload a new document, or a new version of `replaceTarget`. The dialog stays
 * open until the server accepts the file, so a failure is not lost.
 */
export function UploadDialog(props: {
  /** `null` uploads a new document; a document uploads its next version. */
  replaceTarget: DocumentRead | null;
  onClose: () => void;
  onSubmit: (input: UploadInput) => Promise<UiError | null>;
}) {
  const id = useId();
  const replacing = props.replaceTarget !== null;
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (file === null) {
      setFileError("Choose a Markdown or PDF file.");
      return;
    }
    if (!isAcceptedFile(file)) {
      setFileError("Use a Markdown (.md) or PDF (.pdf) file.");
      return;
    }
    setBusy(true);
    setError(null);
    const failure = await props.onSubmit({
      file,
      title: title.trim() === "" ? undefined : title.trim(),
      versionLabel: versionLabel.trim() === "" ? undefined : versionLabel.trim(),
    });
    setBusy(false);
    if (failure === null) props.onClose();
    else setError(failure);
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) props.onClose();
      }}
    >
      <DialogPopup showCloseButton={!busy}>
        <form onSubmit={(event) => void onSubmit(event)} noValidate className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>
              {replacing ? `Replace “${props.replaceTarget?.title}”` : "Upload a document"}
            </DialogTitle>
            <DialogDescription>
              {replacing
                ? "The current version stays active until the new file is indexed."
                : "The assistant can cite the document after it is indexed."}
            </DialogDescription>
          </DialogHeader>
          <DialogPanel className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-file`}>File</Label>
              <Input
                id={`${id}-file`}
                nativeInput
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(",")}
                disabled={busy}
                aria-invalid={fileError ? true : undefined}
                aria-describedby={`${id}-file-hint${fileError ? ` ${id}-file-error` : ""}`}
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setFileError(null);
                }}
              />
              <p id={`${id}-file-hint`} className="m-0 text-xs text-muted-foreground">
                Markdown (.md) or PDF (.pdf).
              </p>
              {fileError ? (
                <p id={`${id}-file-error`} className="m-0 text-xs text-destructive-foreground">
                  {fileError}
                </p>
              ) : null}
            </div>
            {replacing ? null : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-title`}>
                  Title <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <Input
                  id={`${id}-title`}
                  value={title}
                  maxLength={300}
                  disabled={busy}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-version`}>
                Version label <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id={`${id}-version`}
                value={versionLabel}
                maxLength={50}
                disabled={busy}
                aria-describedby={`${id}-version-hint`}
                onChange={(event) => setVersionLabel(event.target.value)}
              />
              <p id={`${id}-version-hint`} className="m-0 text-xs text-muted-foreground">
                For example 2.1. Shown to visitors next to each source.
              </p>
            </div>
            <ActionError error={error} />
          </DialogPanel>
          <DialogFooter>
            <Button variant="outline" onClick={props.onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? <Spinner aria-hidden /> : null}
              {busy ? "Uploading" : replacing ? "Upload new version" : "Upload document"}
            </Button>
          </DialogFooter>
        </form>
      </DialogPopup>
    </Dialog>
  );
}

/** Deleting needs a second, explicit step: it removes every version. */
export function DeleteDialog(props: {
  target: DocumentRead;
  onClose: () => void;
  onConfirm: () => Promise<UiError | null>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<UiError | null>(null);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const failure = await props.onConfirm();
    setBusy(false);
    if (failure === null) props.onClose();
    else setError(failure);
  };

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) props.onClose();
      }}
    >
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete “{props.target.title}”?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the document and all its versions. The assistant stops citing it. This cannot be
            undone.
          </AlertDialogDescription>
          <ActionError error={error} />
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="outline" disabled={busy} />}>Cancel</AlertDialogClose>
          <Button variant="destructive" onClick={() => void confirm()} disabled={busy}>
            {busy ? <Spinner aria-hidden /> : null}
            {busy ? "Deleting" : "Delete document"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogPopup>
    </AlertDialog>
  );
}
