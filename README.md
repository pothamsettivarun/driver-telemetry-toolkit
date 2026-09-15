# Driver Telemetry Toolkit

Reads MoTeC `.ld` files exported from Mu/iRacing and generates:
- Whole-stint lap table + consistency metrics + coaching feedback
- Optional lap comparison vs reference telemetry with manual corner segmentation saved per track

## Requirements
- Python 3.10+ recommended
- pip install -r requirements.txt

## Run (CLI)
python main.py

## Run (GUI)
python gui_app.py

## Notes
- Segmentations are stored in track_segments.json
- This project includes ldparser (GPL-3.0). See NOTICE.md and LICENSE.
