RMR GLOBAL v5.4.1.2C PRODUCT OWNER PACKAGING CORRECTION
PRODUCT OWNER CANDIDATE

WINDOWS-SAFE EXTRACTION
Extract the ZIP to C:\RMR5412C.
The application folder should be C:\RMR5412C\RMR5412.

TO START
1. Make sure Docker Desktop says Engine running.
2. Open C:\RMR5412C\RMR5412.
3. Double-click START-PRODUCT-OWNER-TEST.bat.
4. Leave the launcher open while it verifies package integrity, builds the isolated candidate, runs functional/theme-isolation QC, restarts the application, proves persistence, and opens the browser.

APPLICATION
http://localhost:8089

KERRY PUBLIC WEBSITE
http://localhost:8089/sites/kerry-real-estate

RMR OWNER LOGIN
Email: dave@rmr.local
Password: RMR-Owner-2026!

KERRY CLIENT ADMINISTRATOR
Email: admin@kerry-real-estate.demo
Password: Client-Admin-2026!

WHAT TO TEST FIRST
1. Sign in as RMR Owner and open Kerry Laughlin Real Estate Client 360.
2. Open Client Workspace.
3. On the Dashboard, click each Your growth tools tile: Website, CRM, ProspectIQ, Campaigns & Social, Email & Activities, and Forecasting.
4. Confirm every tile opens its existing destination.
5. Confirm Forecasting fully loads and does not remain on Loading.
6. Return to Kerry Client 360 and confirm the four workspace themes still render exactly as in v5.4.1.1.
7. Sign in as Kerry Client Administrator and repeat the tile-navigation and Forecasting checks.
8. Confirm CAF remains isolated from Kerry.

TO STOP
Double-click STOP-PRODUCT-OWNER-TEST.bat.

TO RESET ONLY THIS ISOLATED ENVIRONMENT
Double-click RESET-PRODUCT-OWNER-DEMO.bat.

IF STARTUP FAILS
Diagnostics are collected automatically in product-owner-data-v5412c\diagnostics.
You may also double-click COLLECT-PRODUCT-OWNER-DIAGNOSTICS.bat.

BOUNDARY
This candidate uses port 8089, Docker project rmr-global-v5412c-product-owner, and product-owner-data-v5412c. It does not overwrite v5.4.1.1 on port 8087, v5.4.1 on port 8086, v5.4.0 on port 8085, or approved v5.3.1 on port 8084. It is not authorized for production or Hasan/Hameer handoff.
