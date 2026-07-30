import { z } from "zod";

export const contactFormSchema = z.object({
  first_name: z.string().min(1, { error: "First name is required" }),
  last_name: z.string().optional(),
  email: z.email({ error: "Invalid email" }).optional().or(z.literal("")),
  phone_number: z.string().min(10, { error: "Phone number must be at least 10 digits" }),
  company_name: z.string().optional(),
  status: z.enum(["new", "contacted", "qualified", "converted", "lost"]),
  tags: z.string().optional(),
  notes: z.string().optional(),
  lead_source_id: z.string().optional(),
  // Which named partner sent this lead. Only collected when the chosen lead
  // source is a referral-partner channel; ignored otherwise.
  referral_partner_id: z.string().optional(),
  birthday: z.string().optional(),
  anniversary: z.string().optional(),
  address_line1: z.string().optional(),
  address_line2: z.string().optional(),
  address_city: z.string().optional(),
  address_state: z.string().optional(),
  address_zip: z.string().optional(),
});

export type ContactFormValues = z.infer<typeof contactFormSchema>;

export const emptyContactFormValues: ContactFormValues = {
  first_name: "",
  last_name: "",
  email: "",
  phone_number: "",
  company_name: "",
  status: "new",
  tags: "",
  notes: "",
  lead_source_id: "",
  referral_partner_id: "",
  birthday: "",
  anniversary: "",
  address_line1: "",
  address_line2: "",
  address_city: "",
  address_state: "",
  address_zip: "",
};
