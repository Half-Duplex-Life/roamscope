#!/usr/bin/env python3
"""Build the one-page RoamScope setup guide PDF for sharing with teammates."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT

from pathlib import Path
_output = Path(__file__).resolve().parents[1] / "demo-output"
_output.mkdir(exist_ok=True)
OUT = str(_output / "roamscope-setup-guide.pdf")

BG = colors.HexColor("#0f1216")
CARD = colors.HexColor("#f2f4f7")
CODE_BG = colors.HexColor("#eef1f4")
ACCENT = colors.HexColor("#1f6feb")
INK = colors.HexColor("#1a1d21")
MUTED = colors.HexColor("#5a6472")

sTitle = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                        textColor=INK, spaceAfter=2)
sSub = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5,
                      textColor=MUTED, spaceAfter=8)
sH = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11,
                    textColor=INK, spaceBefore=8, spaceAfter=4)
sB = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=13,
                    textColor=INK, spaceAfter=2, leftIndent=12)
sB0 = ParagraphStyle("b0", parent=sB, leftIndent=0)
sCode = ParagraphStyle("code", fontName="Courier", fontSize=8.8, leading=12,
                       textColor=INK)
sFoot = ParagraphStyle("foot", fontName="Helvetica", fontSize=8,
                       textColor=MUTED, spaceBefore=8)


def code_block(lines):
    if isinstance(lines, str):
        lines = [lines]
    rows = [[Paragraph("<font face=\"Courier\" size=\"8.8\">%s</font>" % l, sCode)]
            for l in lines]
    t = Table(rows, colWidths=[7.3 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def bullet(text):
    return Paragraph("•&nbsp;&nbsp;" + text, sB)


story = [
    Paragraph("RoamScope — Wi-Fi Roaming Capture", sTitle),
    Spacer(1, 6),
    Paragraph("Sample your MacBook's Wi-Fi every couple of seconds — RSSI, SNR, roam "
              "timestamps — and get graphs plus CSVs. One folder, no installer, no admin rights.",
              sSub),
    HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d5dae0"),
               spaceAfter=2),

    Paragraph("Setup — macOS (~5 minutes, once)", sH),
    Paragraph("<b>1.</b>&nbsp;&nbsp;Install Python via Homebrew (skip if "
              "<font face=\"Courier\">python3 --version</font> already works):", sB),
    code_block("brew install python"),
    Paragraph("<b>2.</b>&nbsp;&nbsp;Unzip <font face=\"Courier\">roamscope.zip</font>, "
              "open Terminal (<font face=\"Courier\">Cmd+Space</font> → Terminal), then:", sB),
    code_block(["cd ~/Downloads/roamscope",
                "python3 -m venv .venv && source .venv/bin/activate",
                "pip install matplotlib"]),
    Paragraph("Each new Terminal session, repeat the <font face=\"Courier\">cd</font> "
              "and <font face=\"Courier\">source .venv/bin/activate</font> lines before running.",
              sB),

    Paragraph("Try it — 30 seconds, no Wi-Fi needed", sH),
    code_block("python roamscope.py --simulate --duration 30"),
    Paragraph("A <font face=\"Courier\">report.html</font> page opens in your browser with "
              "stat cards, five graphs, and the roam table. That's the whole UI: "
              "Terminal is the cockpit, the browser page is the dashboard.", sB0),

    Paragraph("Real capture — 5-minute walk test", sH),
    code_block("python roamscope.py --duration 300"),
    Paragraph("Walk around with the MacBook, come back, hit <font face=\"Courier\">Ctrl+C</font> — "
              "the report builds from your actual radio.", sB0),

    Paragraph("Survey walk — 1–2 hours, full floor", sH),
    code_block("caffeinate -i python roamscope.py --duration 0 --interval 2 --csv --name floor-3"),
    bullet("<b><font face=\"Courier\">--duration 0</font></b> = runs until <i>you</i> press "
           "<font face=\"Courier\">Ctrl+C</font>; it never stops mid-survey."),
    bullet("<b><font face=\"Courier\">caffeinate -i</font></b> keeps the Mac awake so a closed "
           "lid / idle sleep can't kill a 2-hour walk."),
    bullet("<b><font face=\"Courier\">--csv</font></b> exports everything; "
           "<b><font face=\"Courier\">--name floor-3</font></b> labels the files per walk."),

    Paragraph("What you get (in the roamscope folder)", sH),
    bullet("<b><font face=\"Courier\">report.html</font></b> — graphs + roam table (opens automatically)."),
    bullet("<b><font face=\"Courier\">roamscope-&lt;name&gt;-&lt;timestamp&gt;.sqlite</font></b> — raw database."),
    bullet("<b><font face=\"Courier\">…-samples.csv</font></b> every sample (time, BSSID, RSSI, noise, "
           "channel, band, TX rate) · <b><font face=\"Courier\">…-roams.csv</font></b> every roam "
           "(time, from → to, dB change, dwell, reason) · <b><font face=\"Courier\">…-scans.csv</font></b> "
           "neighbor AP snapshots."),

    Paragraph("Notes", sH),
    bullet("Stay on Wi-Fi (not ethernet) during captures. Add <font face=\"Courier\">--live</font> "
           "and open <font face=\"Courier\">http://127.0.0.1:8899/report.html</font> to watch graphs "
           "build while you walk."),
    bullet("Also runs on Windows (<font face=\"Courier\">netsh</font>), Linux (<font face=\"Courier\">iw</font>), "
           "and Android via Termux. iOS can't do this — Apple blocks Wi-Fi signal APIs for third-party apps."),

    Paragraph("RoamScope 1.0 · Share this guide + <font face=\"Courier\">roamscope.zip</font> · "
              "Questions? Ask the person who sent you this.", sFoot),
]

doc = SimpleDocTemplate(OUT, pagesize=letter,
                        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                        topMargin=0.5 * inch, bottomMargin=0.45 * inch,
                        title="RoamScope Setup Guide", author="RoamScope")
doc.build(story)
print("wrote", OUT)
