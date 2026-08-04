# FinanceHub Offline Edition

This package contains two independent FinanceHub applications:

1. **Flask website** — run `python app.py` from the project root. It continues using `expenses.db` exactly as before.
2. **Offline Flutter mobile app** — stored in `mobile`. It uses an on-device SQLite database and requires no server or internet connection.

## Create the offline Android APK

```powershell
cd mobile
Set-ExecutionPolicy -Scope Process Bypass
.\setup_mobile.ps1
flutter build apk --release
```

Share this file with an Android user:

```text
mobile\build\app\outputs\flutter-apk\app-release.apk
```

The recipient can install the APK, create an account, and use every mobile feature independently. Each phone stores separate data. Uninstalling the application may delete that phone's FinanceHub records, so reports should be exported before uninstalling.
