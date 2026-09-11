# Thermal Label Printer

Web app for converting eBay shipping label PDFs to 4x6 thermal labels and printing to a TSPL-compatible thermal printer. Also includes a packing slip generator for BThrifty Online.

## Features

- Upload eBay shipping label PDFs via web interface
- Auto-detects label region on any page size using pixel analysis
- Rotates landscape labels 90° for portrait 4×6 printing
- Scales to fit inside 4×6 label (no distortion, no cutoff)
- Live preview of processed label before printing
- Prints to CUPS thermal printer queue
- Packing slip generator (`gen_packing_slip.py`) for BThrifty Online

## Requirements

- Python 3.12+
- CUPS (for printer queue management)
- A TSPL-compatible thermal label printer (tested with YXWL Y42BT)

### Python Dependencies

```bash
pip3 install flask pymupdf pillow numpy
```

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/zachsplat/Thermalprinter.git
cd Thermalprinter
```

### 2. Install Python dependencies

```bash
pip3 install flask pymupdf pillow numpy
```

### 3. Set up the CUPS printer queue

The app expects a CUPS printer queue named `Y42BT_TSPL` with a 4×6 inch page size (`w288h432`).

The `driver/` directory contains the required files:

- `Y42BT_TSPL.ppd` — PPD file for the YXWL Y42BT thermal printer
- `xprinter-tspl` — CUPS filter (Python) that converts PDF to TSPL commands

Install the filter and create the queue:

```bash
# Install the CUPS filter
sudo cp driver/xprinter-tspl /usr/lib/cups/filter/xprinter-tspl
sudo chmod +x /usr/lib/cups/filter/xprinter-tspl

# Create the printer queue (adjust USB URI for your device)
lpadmin -p "Y42BT_TSPL" -E -v "usb:///Y42BT?serial=0000000" -P driver/Y42BT_TSPL.ppd
```

Verify the printer is detected:

```bash
lpinfo -v
lpstat -p Y42BT_TSPL
```

### 4. Run the app

```bash
python3 app.py
```

The app listens on `0.0.0.0:5000` (all interfaces).

### 5. (Optional) Run as a systemd service

Create `/etc/systemd/system/label-printer.service`:

```ini
[Unit]
Description=Label Printer Web App
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/Thermalprinter
ExecStart=/usr/bin/python3 /path/to/Thermalprinter/app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable label-printer.service
sudo systemctl start label-printer.service
```

### 6. (Optional) Access via Tailscale

The app binds to `0.0.0.0:5000`, so if Tailscale is running on the host, you can access it from any device on your tailnet:

```
http://<tailscale-ip>:5000
```

Check your Tailscale IP with:

```bash
tailscale ip -4
```

## Usage

1. Open the web app in your browser
2. Upload an eBay shipping label PDF
3. Preview the processed 4×6 label
4. Click Print to send to the thermal printer

## Files

- `app.py` — Flask web application
- `templates/index.html` — Web UI
- `gen_packing_slip.py` — Packing slip PDF generator for BThrifty Online
- `test_app.py` — Test suite
- `driver/Y42BT_TSPL.ppd` — PPD file for the YXWL Y42BT thermal printer
- `driver/xprinter-tspl` — CUPS filter (PDF → TSPL)

## License

Private repository. All rights reserved.
