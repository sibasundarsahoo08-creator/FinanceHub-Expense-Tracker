# FinanceHub Web + Offline Mobile Project

This package contains:

- The original Flask website and `expenses.db`
- The original optional Flask mobile API
- A fully offline Flutter application under `mobile/`
- On-device SQLite accounts and financial records
- Offline receipts, recurring transactions, reports and exports

## Run the website

The website is unchanged:

```powershell
python -m pip install -r requirements.txt
python app.py
```

## Prepare and run the offline mobile application

```powershell
cd mobile
Set-ExecutionPolicy -Scope Process Bypass
.\setup_mobile.ps1
flutter run
```

The mobile app does not need `python app.py`, an IP address, USB forwarding, Wi-Fi or an API URL.

## Create the APK to share

```powershell
flutter build apk --release
```

Send `mobile\build\app\outputs\flutter-apk\app-release.apk` to your friend. After installation, the recipient creates a local account and uses the app independently.

See [OFFLINE_MOBILE_README.md](OFFLINE_MOBILE_README.md) and [mobile/README.md](mobile/README.md) for details.
