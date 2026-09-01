import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { contactStatusDotColors } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { contactDisplayName } from "@/lib/utils/contact-name";
import { getContactInitials } from "@/lib/utils/initials";
import type { Contact } from "@/types";

interface ContactHeaderProps {
  contact: Contact;
}

export function ContactHeader({ contact }: ContactHeaderProps) {
  const displayName = contactDisplayName(contact);

  return (
    <div className="flex flex-col items-center text-center space-y-3">
      <Avatar className="h-20 w-20">
        <AvatarImage
          src={contact.avatar_url}
          alt={displayName || "Contact"}
          size={160}
        />
        <AvatarFallback className="bg-primary/10 text-primary text-2xl font-semibold">
          {getContactInitials(contact)}
        </AvatarFallback>
      </Avatar>
      <div>
        <h2 className="text-xl font-semibold">{displayName}</h2>
        {contact.company_name && (
          <p className="text-sm text-muted-foreground">{contact.company_name}</p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div className={cn("h-2 w-2 rounded-full", contactStatusDotColors[contact.status])} />
        <Badge variant="secondary" className="capitalize">
          {contact.status}
        </Badge>
      </div>
    </div>
  );
}
