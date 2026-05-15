"use client";

import * as React from "react";
import { Send, Paperclip, Mic, PhoneOutgoing, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PhoneNumber } from "@/types/phone";

interface MessageComposerProps {
  message: string;
  onMessageChange: (value: string) => void;
  onSend: () => void;
  isSending: boolean;
  phoneNumbers: PhoneNumber[];
  selectedFromNumber: string | undefined;
  onFromNumberChange: (value: string) => void;
}

export function MessageComposer({
  message,
  onMessageChange,
  onSend,
  isSending,
  phoneNumbers,
  selectedFromNumber,
  onFromNumberChange,
}: MessageComposerProps) {
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="p-4 border-t shrink-0">
      {/* Phone number selector */}
      {phoneNumbers.length > 1 && (
        <div className="flex items-center gap-2 mb-2">
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
      <div className="flex items-end gap-2">
        <Button
          size="icon"
          variant="ghost"
          className="h-9 w-9 shrink-0"
          disabled={isSending}
          aria-label="Attach file"
        >
          <Paperclip className="h-4 w-4" />
        </Button>
        <div className="flex-1 relative">
          <Textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => onMessageChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            className="min-h-[40px] max-h-[120px] resize-none pr-12"
            rows={1}
            disabled={isSending}
          />
          <Button
            size="icon"
            variant="ghost"
            className="absolute right-1 bottom-1 h-8 w-8"
            disabled={isSending}
            aria-label="Voice message"
          >
            <Mic className="h-4 w-4" />
          </Button>
        </div>
        <Button
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={onSend}
          disabled={!message.trim() || isSending}
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
