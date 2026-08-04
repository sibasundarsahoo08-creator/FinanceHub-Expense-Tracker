# FinanceHub Store Publishing Checklist

## 1. Backend production readiness

- Deploy the Flask project at a permanent HTTPS domain.
- Set a long random `SECRET_KEY` environment variable.
- Use a hosting plan with persistent storage for `expenses.db` and `static/uploads`, or migrate to a managed production database and object storage before supporting many users.
- Back up financial records and receipts.
- Test every `/api/mobile` endpoint through the public domain.
- Rebuild the app with `--dart-define=API_BASE_URL=https://YOUR-DOMAIN.com/api/mobile`.

## 2. Required identity

- App name: `FinanceHub`
- Android application ID: `com.sibasahoo.financehub`
- iOS bundle ID: `com.sibasahoo.financehub`
- Initial version: `1.0.0+1`

Do not publish a different app using the same identifiers.

## 3. Store assets to prepare

- 1024×1024 app icon without transparency for Apple
- Android adaptive icon foreground and background
- Phone screenshots for Android and iPhone
- Short description, full description and feature graphic
- Support email and public support page
- Hosted Privacy Policy URL
- Demo account for the Apple review team if requested

## 4. Privacy declarations

Declare account contact information, user-entered financial information, user content/receipts and authentication identifiers accurately in both stores. FinanceHub includes in-app permanent account deletion under Settings.

## 5. Google Play

- Create and verify the developer account.
- Create the app and complete Data Safety/content-rating forms.
- Configure app signing.
- Upload the release Android App Bundle (`.aab`).
- If the account is a new personal account, complete the required closed test before requesting production access.

## 6. Apple App Store

- Enroll in the Apple Developer Program.
- Register the bundle ID and create the App Store Connect record.
- On a Mac, select the signing team in Xcode and create an archive.
- Upload through Xcode or Transporter.
- Complete App Privacy, age rating, review information and export-compliance questions.
- Test first through TestFlight, then submit for App Review.
