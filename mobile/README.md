# FinanceHub Offline Mobile

FinanceHub Offline is a Flutter application for Android and iPhone. It stores all accounts and financial records in a private SQLite database on the device. The mobile app does not contact Flask, Python, Wi-Fi, or any web server.

The permanent application identifier is `com.sibasahoo.financehub`.

## Offline features

- Local registration and password-protected login
- Monthly income, expense, balance and transaction dashboard
- Cash, PhonePe/UPI, debit card, credit card and bank transfer tracking
- Expense search, filters, editing and receipt attachments
- Monthly budgets and budget progress
- Savings goals and contributions
- Recurring expenses and income
- Date-range financial reports
- Offline PDF, Excel and CSV generation and sharing
- Permanent account and data deletion

Every installation has its own private database. Data is not synchronized between phones. Export important records before uninstalling because Android may remove local data when the app is uninstalled.

## One-time Windows setup

Open PowerShell inside this `mobile` folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_mobile.ps1
```

The script generates the Android and iOS platform folders, installs packages and runs Flutter analysis.

## Run on your Android phone

Enable USB debugging, connect the phone, and run:

```powershell
flutter devices
flutter run
```

No `python app.py`, ADB reverse, IP address, Wi-Fi, API URL or server is required.

## Build the APK for a friend

```powershell
flutter clean
flutter pub get
flutter build apk --release
```

Send this file:

```text
build\app\outputs\flutter-apk\app-release.apk
```

Your friend can install the APK, create a local account and use FinanceHub without any connection to your computer.

## Website remains separate

The parent project still contains `app.py`, templates and the web database. Run the website exactly as before:

```powershell
python app.py
```

Website data and mobile data are intentionally separate.
