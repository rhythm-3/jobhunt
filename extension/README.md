# OfferPilot Form Filler (browser extension)

Fills your contact details and, optionally, a prepared cover letter on job application pages.

1. Start OfferPilot on this computer (`python3 run.py`).
2. Open `chrome://extensions`, switch on **Developer mode**, click **Load unpacked** and choose this folder.
3. On an application page, click the extension icon, pick the application (for its cover letter), and press **Fill this form**.

What it will not do: press Submit, upload files, or answer salary, visa, notice-period, demographic or consent questions.
It only talks to the app on your own computer (`http://127.0.0.1:8000` by default).
