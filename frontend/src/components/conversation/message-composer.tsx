"use client";

import { Loader2, Mic, Paperclip, PhoneOutgoing, Send, X } from "lucide-react";
import NextImage from "next/image";
import { useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  MMS_IMAGE_ACCEPT,
  prepareOutboundMmsImage,
  type OutboundMmsImage,
} from "@/lib/messaging/image-upload";
import type { PhoneNumber } from "@/types/phone";

interface MessageComposerProps {
  message: string;
  onMessageChange: (value: string) => void;
  onSend: (imageDataUrl?: string) => Promise<void>;
  isSending: boolean;
  phoneNumbers: PhoneNumber[];
  selectedFromNumber: string | undefined;
  onFromNumberChange: (value: string) => void;
  textOnly?: boolean;
}

export function MessageComposer({
  message,
  onMessageChange,
  onSend,
  isSending,
  phoneNumbers,
  selectedFromNumber,
  onFromNumberChange,
  textOnly = false,
}: MessageComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [image, setImage] = useState<OutboundMmsImage | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [isPreparingImage, setIsPreparingImage] = useState(false);

  const selectedPhone = phoneNumbers.find(
    (phone) => phone.phone_number === selectedFromNumber,
  );
  const effectiveImage = textOnly ? null : image;
  const canSendMms =
    !textOnly && selectedPhone?.mms_enabled === true && selectedPhone.provider !== "mac_relay";
  const canSend =
    (!!message.trim() || !!effectiveImage) &&
    !isSending &&
    !isPreparingImage &&
    (!effectiveImage || canSendMms);

  const handleSend = async () => {
    if (!canSend) return;
    try {
      await onSend(effectiveImage?.dataUrl);
      setImage(null);
      setImageError(null);
    } catch {
      // The feed restores the draft and shows the API error; keep the image selected.
    }
  };

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  };

  const handleImageChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setImageError(null);
    setIsPreparingImage(true);
    try {
      setImage(await prepareOutboundMmsImage(file));
    } catch (error) {
      setImage(null);
      setImageError(error instanceof Error ? error.message : "That image could not be attached.");
    } finally {
      setIsPreparingImage(false);
    }
  };

  return (
    <div className="shrink-0 border-t p-4">
      {!textOnly && phoneNumbers.length > 1 && (
        <div className="mb-2 flex items-center gap-2">
          <PhoneOutgoing className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Send from:</span>
          <Select value={selectedFromNumber} onValueChange={onFromNumberChange}>
            <SelectTrigger size="sm" className="h-7 text-xs">
              <SelectValue placeholder="Select number" />
            </SelectTrigger>
            <SelectContent>
              {phoneNumbers.map((phone) => (
                <SelectItem key={phone.id} value={phone.phone_number}>
                  {phone.phone_number}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {!textOnly && image && (
        <div className="mb-2 flex w-fit max-w-full items-center gap-2 rounded-lg border bg-muted/40 p-2">
          <NextImage
            src={image.dataUrl}
            alt="Image attachment preview"
            width={56}
            height={56}
            unoptimized
            className="size-14 rounded-md object-cover"
          />
          <div className="min-w-0">
            <p className="max-w-52 truncate text-sm font-medium">{image.name}</p>
            <p className="text-xs text-muted-foreground">
              {(image.sizeBytes / 1024).toFixed(0)} KB · MMS image
            </p>
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="size-8 shrink-0"
            onClick={() => {
              setImage(null);
              setImageError(null);
            }}
            disabled={isSending}
            aria-label="Remove image attachment"
          >
            <X className="size-4" />
          </Button>
        </div>
      )}

      {!textOnly && image && !canSendMms && (
        <p className="mb-2 text-xs text-destructive" role="alert">
          The selected sending number does not support MMS.
        </p>
      )}
      {!textOnly && imageError && (
        <p className="mb-2 text-xs text-destructive" role="alert">
          {imageError}
        </p>
      )}

      {!textOnly && (
        <input
          ref={imageInputRef}
          type="file"
          accept={MMS_IMAGE_ACCEPT}
          className="hidden"
          onChange={(event) => void handleImageChange(event)}
          aria-label="Choose image attachment"
        />
      )}

      <div className="flex items-end gap-2">
        {!textOnly && (
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-9 w-9 shrink-0"
            onClick={() => imageInputRef.current?.click()}
            disabled={isSending || isPreparingImage || !canSendMms}
            aria-label="Attach image"
            title={canSendMms ? "Attach image" : "Selected number does not support MMS"}
          >
          {isPreparingImage ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Paperclip className="h-4 w-4" />
          )}
          </Button>
        )}
        <div className="relative flex-1">
          <Textarea
            ref={textareaRef}
            value={message}
            onChange={(event) => onMessageChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={image ? "Add a caption..." : "Type a message..."}
            className="min-h-[40px] max-h-[120px] resize-none pr-12"
            rows={1}
            disabled={isSending}
          />
          {!textOnly && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="absolute right-1 bottom-1 h-8 w-8"
              disabled={isSending}
              aria-label="Voice message"
            >
              <Mic className="h-4 w-4" />
            </Button>
          )}
        </div>
        <Button
          type="button"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={() => void handleSend()}
          disabled={!canSend}
          aria-label="Send message"
        >
          {isSending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
}
