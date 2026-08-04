$ErrorActionPreference = "Stop"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter is not installed or is not available in PATH. Install Flutter, reopen PowerShell, and run this script again."
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
$backupRoot = Join-Path $env:TEMP ("financehub-mobile-source-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $backupRoot | Out-Null
Copy-Item "pubspec.yaml" $backupRoot
Copy-Item "analysis_options.yaml" $backupRoot
Copy-Item "lib" $backupRoot -Recurse

flutter create --org com.sibasahoo --project-name financehub_mobile --platforms android,ios .
if ($LASTEXITCODE -ne 0) { throw "Flutter project creation failed." }

Copy-Item (Join-Path $backupRoot "pubspec.yaml") "pubspec.yaml" -Force
Copy-Item (Join-Path $backupRoot "analysis_options.yaml") "analysis_options.yaml" -Force
Copy-Item (Join-Path $backupRoot "lib\*") "lib" -Recurse -Force

# Use the same permanent identifier on Android and iOS.
Get-ChildItem "android", "ios" -Recurse -File | ForEach-Object {
    $text = Get-Content $_.FullName -Raw
    $updated = $text.Replace("com.sibasahoo.financehub_mobile", "com.sibasahoo.financehub")
    $updated = $updated.Replace("com.sibasahoo.financehubMobile", "com.sibasahoo.financehub")
    if ($updated -ne $text) {
        Set-Content $_.FullName $updated -Encoding UTF8
    }
}

$gradleFile = "android\app\build.gradle.kts"
$gradleText = Get-Content $gradleFile -Raw
$gradleText = $gradleText.Replace(
    "jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17",
    "jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)"
)
Set-Content $gradleFile $gradleText -Encoding UTF8

$manifest = "android\app\src\main\AndroidManifest.xml"
$manifestText = Get-Content $manifest -Raw
if ($manifestText -notmatch "android.permission.INTERNET") {
    $manifestText = $manifestText -replace "(<manifest[^>]*>)", "`$1`r`n    <uses-permission android:name=`"android.permission.INTERNET`" />"
}
$manifestText = $manifestText.Replace('android:label="financehub_mobile"', 'android:label="FinanceHub"')
Set-Content $manifest $manifestText -Encoding UTF8

$widgetTest = @'
import 'package:flutter_test/flutter_test.dart';
import 'package:financehub_mobile/main.dart';

void main() {
  testWidgets('FinanceHub starts', (tester) async {
    await tester.pumpWidget(const FinanceHubApp());
    expect(find.text('FinanceHub'), findsWidgets);
  });
}
'@
Set-Content "test\widget_test.dart" $widgetTest -Encoding UTF8

flutter pub get
if ($LASTEXITCODE -ne 0) { throw "Flutter package installation failed." }
flutter analyze
if ($LASTEXITCODE -ne 0) { throw "Flutter analysis found errors." }

Write-Host ""
Write-Host "FinanceHub Offline setup complete." -ForegroundColor Green
Write-Host "Run on a connected Android phone with:"
Write-Host "flutter run"
Write-Host "Build the shareable APK with:"
Write-Host "flutter build apk --release"
