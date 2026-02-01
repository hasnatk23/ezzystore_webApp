# Ezzystore WebApp (Flask + SQLite)

## Default Admin Login
- Username: admin
- Password: admin123

Only the built-in admin account can access the dashboard. From there you can add shops and assign exactly one manager per shop. Manager accounts are used for assignment records only and cannot sign in.

## Run
1) Install dependencies:
   pip install -r requirements.txt

2) Start server:
   python run.py

Open:
http://127.0.0.1:5000/login

## Invoice Printing & Sharing

### Dependencies
- `python-escpos` for ESC/POS printing
- `reportlab` for PDF generation

Install:
```
pip install -r requirements.txt
```

### Printer Settings
Go to Manager > Settings and set:
- Printer width (mm)
- Printer height (mm)

### Printer Connection (Backend)
Configure environment variables:

USB printer:
```
set PRINTER_MODE=usb
set PRINTER_VENDOR_ID=0x1234
set PRINTER_PRODUCT_ID=0x5678
```

Network printer:
```
set PRINTER_MODE=network
set PRINTER_IP=192.168.1.50
set PRINTER_PORT=9100
```

### Endpoints
- Print: `POST /invoices/{sale_id}/print`
- Share PDF: `GET /invoices/{sale_id}/share.pdf`
- Share Text: `GET /invoices/{sale_id}/share.txt`

### Troubleshooting
- If printing fails: verify VID/PID or IP/port and ensure the backend runs on the same machine as the USB printer.
- If PDF fails: ensure `reportlab` is installed.
