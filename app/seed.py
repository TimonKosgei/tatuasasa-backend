import os
import sys
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client

# 1. Load your existing .env file
# This assumes your .env is in the root directory (tatuasasa)
load_dotenv()

import os
from dotenv import load_dotenv
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)
# 2. Safety check to make sure keys are loaded before starting
if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    print("[CRITICAL] Missing environment keys! Ensure SUPABASE_URL, SUPABASE_KEY, and GEMINI_API_KEY are in your .env file.")
    sys.exit(1)

# Initialize Clients
# Pass http_options to force the stable v1 API version

ai_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={'api_version': 'v1'}
)



# 3. Categorized knowledge base articles from your documentation
documents_to_seed = [
    {
        "title": "How to install a printer by IP Address on macOS",
        "category": "printers",
        "content": (
            "Instructions to install an enterprise network printer via IP address on macOS:\n"
            "1. Open Safari and navigate to the printer directory server at: http://tru-univ-ps1.tru.univ/printers\n"
            "2. Search for the target printer and document its exact 'Name' and network IP address from the 'Location' column "
            "(e.g., Name: OL140_1-TOS203, IP: 206.123.169.85).\n"
            "3. Navigate to the Apple Menu in the top left corner and select 'System Preferences...'.\n"
            "4. Select the 'Print & Scan' hardware utility icon.\n"
            "5. Click the plus '+' sign at the bottom of the printer list panel to add a new device.\n"
            "6. Select the 'IP' globe icon in the top toolbar of the Add Printer window.\n"
            "7. Set the Protocol to 'Line Printer Daemon - LPD', enter the documented IP address in the 'Address' field, "
            "and input the exact printer identifier in the 'Name' field.\n"
            "8. Click 'Add', verify the printer configuration layout matches, and click 'OK' to finalize the installation.\n"
            "9. Note: If multiple printers are installed, toggle the default device using the 'Default Printer' drop-down menu."
        )
    },
    {
        "title": "Printer Troubleshooting - Application Print Jobs & Spooler Errors",
        "category": "printers",
        "content": (
            "Problem: An application document does not print, or a print spooler error occurs preventing additions.\n"
            "Probable Causes:\n"
            "- There is a corrupted document hanging in the active print queue.\n"
            "- The system print spooler service has stopped running properly.\n"
            "- The printer has been mapped to an incorrect hardware port allocation.\n"
            "Possible Solutions:\n"
            "1. Access the print queue interface, manually cancel/purge the stuck document, and attempt to print again.\n"
            "2. Open system services, restart the local print spooler service, and reboot the workstation if necessary.\n"
            "3. Access printer properties settings to verify and reconfigure the designated printer port assignment."
        )
    },
    {
        "title": "Printer Troubleshooting - Hardware Standby, Cables, and Media Errors",
        "category": "printers",
        "content": (
            "Problem: Print queue functions normally, but the physical printer does not print anything.\n"
            "Probable Causes:\n"
            "- Loose or damaged physical interface cabling (bent pins on the printer cable lines).\n"
            "- The physical printer has entered an inactive standby or sleep mode state.\n"
            "- The hardware unit is reporting an active environmental error condition (out of paper, out of toner, or a paper jam).\n"
            "Possible Solutions:\n"
            "1. Inspect for bent pins on the printer cable and secure all hardware connections firmly to the computer and printer.\n"
            "2. Manually interact with the physical control panel to resume from standby, or power cycle the machine completely.\n"
            "3. Check the physical hardware LCD status display panel and clear any media blocks, add paper, or replace depleted toner."
        )
    },
    {
        "title": "Printer Troubleshooting - Garbled Characters and Outdated Drivers",
        "category": "printers",
        "content": (
            "Problem: Printer prints unknown, garbled characters or completely fails to execute a standard test alignment page.\n"
            "Probable Causes:\n"
            "- An incorrect, corrupted, or outdated printer driver package is currently active on the host machine.\n"
            "- The printer is plugged directly into an unstable Uninterruptible Power Supply (UPS) instead of standard line voltage.\n"
            "Possible Solutions:\n"
            "1. Completely uninstall the current active print driver software from the operating system.\n"
            "2. Download and install the verified, up-to-date manufacturer driver software built for the exact model.\n"
            "3. Isolate electrical issues by moving the printer power cable out of the UPS and plugging it directly into a wall outlet or high-quality surge protector."
        )
    },
    {
        "title": "Printer Troubleshooting - Paper Jams and Media Creasing",
        "category": "printers",
        "content": (
            "Problem: Paper consistently jams inside the machine assembly, creases during feed passes, or fails to feed entirely.\n"
            "Probable Causes:\n"
            "- Internal roller elements or feed tracks are dirty or contaminated with paper dust.\n"
            "- High ambient humidity is causing sheets in the paper tray to stick together.\n"
            "- Workstation print settings specify a different paper size than what is physically loaded in the input tray.\n"
            "Possible Solutions:\n"
            "1. Power down the device and perform a thorough internal cleaning of rollers using recommended kits.\n"
            "2. Remove wrinkled, damp, or defective paper stock. Flex and fan a fresh batch of dry manufacturer-recommended paper before loading.\n"
            "3. Adjust the software print dialogue properties settings to ensure matching target paper sizes."
        )
    },
    {
        "title": "Printer Troubleshooting - Faded Prints and Toner Fusing Failures",
        "category": "printers",
        "content": (
            "Problem: Executed print jobs appear completely faded, or loose toner is lifting and not fusing to the paper surface.\n"
            "Probable Causes:\n"
            "- The internal toner cartridge is completely empty, low on powder, or structurally defective.\n"
            "- The paper medium in use is entirely incompatible with the thermal properties of the printing unit.\n"
            "Possible Solutions:\n"
            "1. Extract the active toner cartridge assembly and replace it with a fresh, verified replacement unit.\n"
            "2. Verify media specifications and replace existing stock with paper officially supported by the printer manufacturer."
        )
    },
    {
        "title": "Printer Troubleshooting - Blank Pages, Missing Displays, and Access Denied",
        "category": "printers",
        "content": (
            "Problem: Printer outputs completely blank pages, user receives 'Access Denied' installation notices, or the hardware display screen is totally dark.\n"
            "Probable Causes:\n"
            "- Severe internal component failures such as a clogged ink head, failed corona wire, or broken high-voltage power supply.\n"
            "- The operating system user profile lacks local administrative or power user execution privileges.\n"
            "- The hardware unit is turned off, display screen contrast is down, or the LCD screen panel is physically broken.\n"
            "Possible Solutions:\n"
            "1. Isolate blank page output: perform a software print head clean cycle. If unresolved, replace the corona wire or internal high-voltage power supply board.\n"
            "2. Overcome Access Denied errors: Log out of the staff profile and re-authenticate as a system administrator to install drivers.\n"
            "3. Ensure the main power switch is turned on, adjust screen contrast controls via the menu buttons, or replace the broken display module."
        )
    }
]

def seed_knowledge_base():
    print(f"Connecting to Supabase database instance...")
    
    for article in documents_to_seed:
        print(f"Vectorizing: {article['title']}...")
        try:
            # Generate the 768-dimension vector embedding via Gemini API
            response = ai_client.models.embed_content(
                model="gemini-embedding-2",
                contents=article["content"],
                config={
        "output_dimensionality": 768
    }
            )
            embedding_vector = response.embeddings[0].values
            
            # Formulate the payload object
            payload = {
                "title": article["title"],
                "content": article["content"],
                "category": article["category"],
                "embedding": embedding_vector 
            }
            
            # Fire data direct to public.official_documentation
            supabase.table("official_documentation").insert(payload).execute()
            print(f"[SUCCESS] Uploaded and indexed: '{article['title']}'")
            
        except Exception as e:
            print(f"[ERROR] Failed to process '{article['title']}': {str(e)}")

if __name__ == "__main__":
    seed_knowledge_base()