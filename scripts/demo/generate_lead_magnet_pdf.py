#!/usr/bin/env python3
"""Generate a clean PDF for the Dead Lead Reactivation Scripts lead magnet."""

from fpdf import FPDF
from pathlib import Path

OUTPUT_DIR = Path("/home/groot/aicrm/backend/static/lead-magnets")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "dead-lead-reactivation-scripts.pdf"


class LeadMagnetPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, "Dead Lead Reactivation Scripts | PRESTYJ", align="C")
            self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def title_page(self):
        self.add_page()
        self.ln(60)

        # Main title
        self.set_font("Helvetica", "B", 32)
        self.set_text_color(0, 0, 0)
        self.cell(0, 15, "Dead Lead", align="C", ln=True)
        self.cell(0, 15, "Reactivation Scripts", align="C", ln=True)

        self.ln(10)

        # Subtitle
        self.set_font("Helvetica", "", 16)
        self.set_text_color(80, 80, 80)
        self.cell(0, 10, "7 Proven Scripts to Wake Up Your Database", align="C", ln=True)

        self.ln(20)

        # Methodology line
        self.set_font("Helvetica", "I", 11)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Combining the best of:", align="C", ln=True)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, "NEPQ (Jeremy Miner) + Value-First (Alex Hormozi) + Reverse Selling (Brandon Mulrenin)", align="C", ln=True)

        self.ln(40)

        # Brought to you by
        self.set_font("Helvetica", "", 10)
        self.set_text_color(128, 128, 128)
        self.cell(0, 8, "Brought to you by PRESTYJ", align="C", ln=True)

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(0, 0, 0)
        self.ln(5)
        self.cell(0, 12, title, ln=True)
        self.ln(3)

    def script_header(self, number: int, title: str, methodology: str):
        # Script number and title
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(0, 0, 0)
        self.cell(0, 10, f"Script #{number}: {title}", ln=True)

        # Methodology tag
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, f"Methodology: {methodology}", ln=True)
        self.ln(3)

    def psychology_box(self, text: str):
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(60, 60, 60)
        self.set_fill_color(245, 245, 245)
        self.multi_cell(0, 6, f"Psychology: {text}", fill=True)
        self.ln(3)

    def script_box(self, text: str):
        self.set_font("Courier", "", 10)
        self.set_text_color(0, 0, 0)
        self.set_fill_color(250, 250, 250)
        self.set_draw_color(200, 200, 200)

        # Draw border
        x, y = self.get_x(), self.get_y()
        self.multi_cell(0, 6, text, fill=True, border=1)
        self.ln(3)

    def why_it_works(self, points: list[str]):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 6, "Why it works:", ln=True)

        self.set_font("Helvetica", "", 10)
        for point in points:
            self.cell(5)
            self.cell(0, 6, f"* {point}", ln=True)
        self.ln(5)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 6, text)
        self.ln(3)

    def divider(self):
        self.ln(5)
        self.set_draw_color(200, 200, 200)
        self.line(20, self.get_y(), 190, self.get_y())
        self.ln(8)


def create_pdf():
    pdf = LeadMagnetPDF()

    # Title page
    pdf.title_page()

    # Why These Scripts Work
    pdf.add_page()
    pdf.section_title("Why These Scripts Work")

    pdf.body_text(
        "Most agents blast their old leads with desperate messages like:\n"
        "- \"Just checking in!\"\n"
        "- \"Still looking to buy/sell?\"\n"
        "- \"I have a great listing for you!\"\n\n"
        "These get ignored because they're seller-focused and predictable."
    )

    pdf.ln(5)
    pdf.body_text(
        "The scripts below use three psychological principles:\n\n"
        "1. NEPQ (Miner): Ask questions that make THEM realize their own need\n\n"
        "2. Value-First (Hormozi): Lead with something genuinely useful\n\n"
        "3. Reverse Selling (Mulrenin): Take away the sale to create desire"
    )

    pdf.divider()

    # Script 1
    pdf.script_header(1, "The Database Cleanup", "Brandon Mulrenin's Reverse Selling")
    pdf.psychology_box("People fear loss more than they desire gain. By suggesting you're removing them, you trigger loss aversion.")

    pdf.script_box(
        "Hey {first_name}, I'm cleaning up my database and noticed\n"
        "we never connected after we first spoke.\n\n"
        "Not sure if buying/selling is even on your radar anymore -\n"
        "totally fine if it's not.\n\n"
        "Should I keep you on my list or go ahead and close out your file?"
    )

    pdf.why_it_works([
        "Pattern interrupt (they expect you to CHASE, not remove)",
        "No pressure (disarms their defenses)",
        "Forces a response (they don't want to be \"closed out\")",
        "Qualifies them (serious people identify themselves)"
    ])

    pdf.divider()

    # Script 2
    pdf.script_header(2, "The Curiosity Question", "Jeremy Miner's NEPQ")
    pdf.psychology_box("Questions create engagement. This gets them talking about their situation without feeling sold to.")

    pdf.script_box(
        "Hey {first_name}, random question for you -\n\n"
        "When we talked a while back, you mentioned wanting to\n"
        "{buy/sell/move}. Just curious, has anything changed with that,\n"
        "or is it still something you're thinking about?"
    )

    pdf.why_it_works([
        "Opens with curiosity (non-threatening)",
        "References past conversation (shows you remember)",
        "Neutral question (not pushing for a yes)",
        "\"Still thinking about\" acknowledges life happens"
    ])

    pdf.add_page()

    # Script 3
    pdf.script_header(3, "The Valuable Intel", "Alex Hormozi's Value-First")
    pdf.psychology_box("Lead with something genuinely useful. No ask, just value. Builds reciprocity and positions you as expert.")

    pdf.script_box(
        "Hey {first_name}, thought of you -\n\n"
        "Just saw {neighborhood} home values jumped 12% this quarter.\n"
        "A few homes near {their area} sold above asking in under a week.\n\n"
        "Not sure if that changes anything for you, but figured\n"
        "you'd want to know."
    )

    pdf.why_it_works([
        "Specific data (not vague \"market is hot\")",
        "Personalized to their area (shows you did homework)",
        "No ask (pure value, no pressure)",
        "\"Not sure if that changes anything\" is Mulrenin's takeaway"
    ])

    pdf.divider()

    # Script 4
    pdf.script_header(4, "The Honest Question", "Jeremy Miner's Problem-Awareness")
    pdf.psychology_box("Gets them to verbalize what's stopping them - saying it out loud often makes them realize it's not a real blocker.")

    pdf.script_box(
        "Hey {first_name}, honest question -\n\n"
        "When we first connected, you seemed pretty interested in\n"
        "{buying/selling}. What ended up happening with that?\n\n"
        "No pressure either way, just curious."
    )

    pdf.why_it_works([
        "\"Honest question\" signals authenticity",
        "Asks what happened (not \"are you still interested\")",
        "\"No pressure\" disarms (Mulrenin technique)",
        "They often talk themselves back into it"
    ])

    pdf.divider()

    # Script 5
    pdf.script_header(5, "The \"Found Something\" Tease", "Hormozi Value + Mulrenin Takeaway")
    pdf.psychology_box("Specificity creates curiosity. The takeaway prevents it from feeling salesy.")

    pdf.script_box(
        "Hey {first_name}, this might be a long shot, but...\n\n"
        "I came across a {property type} in {area} that reminded me\n"
        "of what you were looking for. {One detail - big backyard,\n"
        "under $X, quiet street}.\n\n"
        "Probably not what you're looking for anymore, but figured\n"
        "I'd mention it just in case."
    )

    pdf.why_it_works([
        "\"Long shot\" and \"probably not\" = reverse selling",
        "Specific detail proves you remember their criteria",
        "Creates FOMO (what if it IS perfect?)",
        "Low pressure response"
    ])

    pdf.add_page()

    # Script 6
    pdf.script_header(6, "The Permission Close", "All Three Combined")
    pdf.psychology_box("For warmer leads. Combines Miner's commitment questions, Hormozi's specificity, and Mulrenin's takeaway.")

    pdf.script_box(
        "Hey {first_name}, I know we've been talking on and off\n"
        "for a while.\n\n"
        "I don't want to keep bothering you if the timing isn't right.\n"
        "At the same time, I don't want you to miss out if it is.\n\n"
        "Real quick - on a scale of 1-10, how serious are you about\n"
        "{buying/selling} in the next 6 months?"
    )

    pdf.why_it_works([
        "Acknowledges the long timeline (validates them)",
        "\"Don't want to bother you\" = permission to leave (Mulrenin)",
        "\"Don't want you to miss out\" = subtle FOMO (Hormozi)",
        "Scale question = commitment question (Miner)"
    ])

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Follow-up based on their number:", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "1-3: \"Got it, I'll check back in a few months.\"", ln=True)
    pdf.cell(0, 6, "4-6: \"What would need to happen to move that to a 7 or 8?\"", ln=True)
    pdf.cell(0, 6, "7-10: \"Love it. What's been stopping us from getting started?\"", ln=True)

    pdf.divider()

    # Script 7
    pdf.script_header(7, "The Straight Shooter", "Brandon Mulrenin's Radical Honesty")
    pdf.psychology_box("Brutal honesty is the ultimate pattern interrupt. Works when you've followed up multiple times with no response.")

    pdf.script_box(
        "Hey {first_name}, I'm just gonna be real with you.\n\n"
        "I've reached out a few times and haven't heard back.\n"
        "Totally fine if you're not interested - I'd rather know\n"
        "so I'm not bugging you.\n\n"
        "Are you still thinking about {buying/selling}, or should I\n"
        "stop reaching out?"
    )

    pdf.why_it_works([
        "Radical honesty (unexpected from a salesperson)",
        "Gives them permission to say no (reduces pressure)",
        "Binary choice forces a decision",
        "Respectful of their time"
    ])

    # Follow-up Framework
    pdf.add_page()
    pdf.section_title("The Follow-Up Framework")

    pdf.body_text("No matter which script gets a response, use this NEPQ sequence:")

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Step 1: Acknowledge + Question", ln=True)
    pdf.set_font("Courier", "", 10)
    pdf.cell(0, 6, "\"That makes sense. What's been the main thing holding you back?\"", ln=True)

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Step 2: Go Deeper", ln=True)
    pdf.set_font("Courier", "", 10)
    pdf.cell(0, 6, "\"And what happens if that doesn't change in 6-12 months?\"", ln=True)

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Step 3: Solution Awareness", ln=True)
    pdf.set_font("Courier", "", 10)
    pdf.cell(0, 6, "\"If we could solve {their problem}, would that change things?\"", ln=True)

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Step 4: Soft Close", ln=True)
    pdf.set_font("Courier", "", 10)
    pdf.cell(0, 6, "\"Want to hop on a quick call and see if it makes sense?\"", ln=True)

    # Quick Reference
    pdf.add_page()
    pdf.section_title("Quick Reference Card")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(25, 8, "Script", border=1, fill=True, align="C")
    pdf.cell(55, 8, "Best For", border=1, fill=True, align="C")
    pdf.cell(90, 8, "Opening Line", border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)

    data = [
        ("#1", "Cold/old leads", "\"I'm cleaning up my database...\""),
        ("#2", "Anyone", "\"Has anything changed with...\""),
        ("#3", "Warm leads", "\"Just saw {market data}...\""),
        ("#4", "Engaged then quiet", "\"What ended up happening...\""),
        ("#5", "Specific criteria", "\"Came across something...\""),
        ("#6", "Warm, ready to close", "\"Scale of 1-10...\""),
        ("#7", "Multiple no-responses", "\"I'm just gonna be real...\""),
    ]

    for row in data:
        pdf.cell(25, 7, row[0], border=1, align="C")
        pdf.cell(55, 7, row[1], border=1)
        pdf.cell(90, 7, row[2], border=1)
        pdf.ln()

    # CTA Page
    pdf.add_page()
    pdf.ln(40)

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 12, "Want to Automate This?", align="C", ln=True)

    pdf.ln(10)

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 7,
        "Our AI can send these scripts to your entire database,\n"
        "handle all the responses, qualify the leads,\n"
        "and book appointments on your calendar -\n"
        "all while you focus on closings.",
        align="C"
    )

    pdf.ln(15)

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, "Reply \"AUTOMATE\" to learn more", align="C", ln=True)

    pdf.ln(30)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 8, "PRESTYJ - AI-Powered Lead Response & Recovery", align="C", ln=True)

    # Save
    pdf.output(str(OUTPUT_FILE))
    print(f"PDF created: {OUTPUT_FILE}")
    return OUTPUT_FILE


if __name__ == "__main__":
    create_pdf()
